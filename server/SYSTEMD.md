# Operating the interviewer in production

The FastAPI server and ngrok tunnel both run as systemd services so they survive logout and restart on failure.

## Services

- `interviewer.service` — uvicorn on `127.0.0.1:8000`, reads `.env` for the Anthropic key
- `interviewer-ngrok.service` — ngrok tunnel exposing port 8000 to a public URL

Both `enabled` (start on boot) and chained (`interviewer-ngrok` requires `interviewer`).

## Common commands

```bash
# Status
systemctl status interviewer.service interviewer-ngrok.service

# Restart after a code change in /root/interviewer/server
systemctl restart interviewer.service

# Restart ngrok (will get a new URL on free tier — see below)
systemctl restart interviewer-ngrok.service

# Logs
tail -f /var/log/interviewer.log
tail -f /var/log/interviewer-ngrok.log

# Stop everything
systemctl stop interviewer-ngrok.service interviewer.service
```

## ngrok URL management

Free-tier ngrok URLs change every time the tunnel restarts. To grab the current public URL and propagate it into the SvelteKit frontend's `.env`:

```bash
/root/interviewer/server/scripts/sync-ngrok-url.sh
```

Run this after every `systemctl restart interviewer-ngrok.service`. It rewrites `PUBLIC_INTERVIEWER_API` in `/root/idealists-site/.env`.

You'll also need to redeploy the SvelteKit site (or restart `vite dev`) for the new value to take effect — `PUBLIC_*` vars are baked at build time.

For a stable URL, upgrade ngrok to a paid plan and reserve a static domain — then set the tunnel to that domain in `/etc/systemd/system/interviewer-ngrok.service` (e.g. `--domain=interviewer.idealistscollective.org`) and the env var only needs to be set once.

## Updating the prompt or wiki

The system prompt (`prompts/system.md`), the reflector prompt (`prompts/notes.md`), and the always-loaded wiki pages are all read at module import time. After editing any of these, **restart the service**:

```bash
systemctl restart interviewer.service
```

Subsequent sessions will see the new prompt/wiki content.

## Health check

```bash
curl -sS http://127.0.0.1:8000/health           # local
curl -sS -H "ngrok-skip-browser-warning: true" \
  $(curl -sS http://127.0.0.1:4040/api/tunnels \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["tunnels"][0]["public_url"])'\
  )/health                                        # via ngrok
```

Returns `{"ok":true,"anthropic_api_key":true,"active_sessions":N}`.

## Files of interest

- `/etc/systemd/system/interviewer.service`
- `/etc/systemd/system/interviewer-ngrok.service`
- `/root/.config/ngrok/ngrok.yml` — ngrok authtoken
- `/root/interviewer/server/.env` — `ANTHROPIC_API_KEY=...`
- `/var/log/interviewer.log` — server logs
- `/var/log/interviewer-ngrok.log` — tunnel logs
- `/root/interviewer/server/transcripts/` — saved interview transcripts (full message history including tool calls)
- `/root/interviewer/server/notes/` — auto-generated reflector notes (one per session). Drafts are saved as `<basename>.draft.md` when the participant edits.
