import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

let cached: string | null = null;

export async function loadSystemPrompt(): Promise<string> {
  if (cached) return cached;
  const path = resolve(process.cwd(), 'system_prompt.md');
  const raw = await readFile(path, 'utf8');
  // Strip the leading docs section above the `---` divider, if present.
  const idx = raw.indexOf('\n---\n');
  cached = idx >= 0 ? raw.slice(idx + 5).trim() : raw.trim();
  return cached;
}
