<script lang="ts">
  interface Msg {
    role: 'user' | 'assistant';
    content: string;
    toolUses?: { name: string; input: unknown }[];
  }

  let messages = $state<Msg[]>([]);
  let input = $state('');
  let sending = $state(false);
  let error = $state<string | null>(null);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    error = null;
    input = '';

    messages = [...messages, { role: 'user', content: text }];
    const placeholder: Msg = { role: 'assistant', content: '', toolUses: [] };
    messages = [...messages, placeholder];
    sending = true;

    try {
      const res = await fetch('/api/interview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: messages.slice(0, -1).map((m) => ({ role: m.role, content: m.content }))
        })
      });
      if (!res.body) throw new Error('no response body');

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 2);
          if (!line.startsWith('data:')) continue;
          try {
            const { event, data } = JSON.parse(line.slice(5).trim());
            const last = messages[messages.length - 1];
            if (event === 'text') {
              last.content += data;
            } else if (event === 'tool_use') {
              (last.toolUses ??= []).push(data);
            } else if (event === 'error') {
              error = data;
            }
            messages = [...messages]; // reactivity nudge
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (e) {
      error = (e as Error).message;
    } finally {
      sending = false;
    }
  }

  function downloadTranscript() {
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const lines = messages.map((m) => {
      let out = `### ${m.role}\n\n${m.content}`;
      if (m.toolUses?.length) {
        out += '\n\n*' + m.toolUses.map((t) => `tool: ${t.name}`).join(', ') + '*';
      }
      return out;
    });
    const blob = new Blob([`# interview · ${ts}\n\n` + lines.join('\n\n---\n\n')], {
      type: 'text/markdown'
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `interview-${ts}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function startNew() {
    messages = [];
    error = null;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      send();
    }
  }
</script>

<svelte:head>
  <title>idealists interviewer</title>
</svelte:head>

<main>
  <header>
    <h1>idealists interviewer</h1>
    <p class="sub">
      a claude that's read the whole collective and would like to know what you care about, what you
      want to know, and what you're worried about. say hi.
    </p>
    <div class="controls">
      <button onclick={startNew} disabled={sending || messages.length === 0}>start over</button>
      <button onclick={downloadTranscript} disabled={messages.length === 0}>save transcript</button>
    </div>
  </header>

  <section class="chat">
    {#if messages.length === 0}
      <p class="empty">
        type something below to begin. nothing is saved on the server unless you choose to share
        the transcript afterwards.
      </p>
    {/if}

    {#each messages as m, i (i)}
      <article class="msg {m.role}">
        <div class="role">{m.role}</div>
        <div class="content">
          {m.content}
          {#if sending && i === messages.length - 1 && m.role === 'assistant' && !m.content}
            <span class="cursor">▍</span>
          {/if}
        </div>
        {#if m.toolUses?.length}
          <details class="tools">
            <summary>{m.toolUses.length} wiki lookup{m.toolUses.length === 1 ? '' : 's'}</summary>
            {#each m.toolUses as t}
              <code>{t.name}({JSON.stringify(t.input)})</code>
            {/each}
          </details>
        {/if}
      </article>
    {/each}

    {#if error}
      <p class="error">error: {error}</p>
    {/if}
  </section>

  <form class="composer" onsubmit={(e) => { e.preventDefault(); send(); }}>
    <textarea
      bind:value={input}
      onkeydown={onKeydown}
      placeholder="say hi (cmd+enter to send)"
      rows="3"
      disabled={sending}
    ></textarea>
    <button type="submit" disabled={sending || !input.trim()}>send</button>
  </form>
</main>

<style>
  :global(body) {
    margin: 0;
    background: #fbf9f4;
    color: #1c1c1c;
    font-family: ui-serif, Georgia, 'Times New Roman', serif;
    line-height: 1.6;
  }

  main {
    max-width: 44rem;
    margin: 0 auto;
    padding: 2rem 1.25rem 8rem;
  }

  header h1 {
    font-family: ui-sans-serif, system-ui, sans-serif;
    font-size: 1.5rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin: 0 0 0.5rem;
  }

  .sub {
    color: #555;
    margin: 0 0 1rem;
  }

  .controls {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
  }

  button {
    background: #fbf9f4;
    border: 1px solid #1c1c1c;
    padding: 0.35rem 0.7rem;
    font-family: inherit;
    cursor: pointer;
    font-size: 0.9rem;
  }

  button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  button:hover:not(:disabled) {
    background: #1c1c1c;
    color: #fbf9f4;
  }

  .chat {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .msg {
    border-left: 2px solid #ccc;
    padding-left: 1rem;
  }

  .msg.user {
    border-left-color: #6b8e6b;
  }

  .msg.assistant {
    border-left-color: #c08552;
  }

  .role {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #888;
    margin-bottom: 0.25rem;
  }

  .content {
    white-space: pre-wrap;
    word-wrap: break-word;
  }

  .cursor {
    animation: blink 1s steps(2, start) infinite;
  }

  @keyframes blink {
    to {
      visibility: hidden;
    }
  }

  .tools {
    margin-top: 0.4rem;
    font-size: 0.8rem;
    color: #888;
  }

  .tools code {
    display: block;
    font-family: ui-monospace, monospace;
    margin-top: 0.2rem;
    word-break: break-all;
  }

  .empty {
    color: #888;
    font-style: italic;
  }

  .error {
    color: #b04040;
    border-left: 2px solid #b04040;
    padding-left: 1rem;
  }

  .composer {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    background: #fbf9f4;
    border-top: 1px solid #ccc;
    padding: 1rem;
    display: flex;
    gap: 0.5rem;
    justify-content: center;
  }

  .composer textarea {
    flex: 1;
    max-width: 38rem;
    resize: vertical;
    font-family: inherit;
    font-size: 1rem;
    padding: 0.5rem;
    border: 1px solid #1c1c1c;
    background: #fff;
  }

  .composer button {
    align-self: flex-end;
  }
</style>
