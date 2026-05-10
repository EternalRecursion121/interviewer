/**
 * Read-only wiki access for the interviewer agent.
 *
 * Three operations are exposed: list_wiki_pages, search_wiki, read_wiki_page.
 * All paths are resolved relative to the wiki root and rejected if they
 * escape it (path traversal protection).
 */
import { readFile, readdir, stat } from 'node:fs/promises';
import { join, relative, resolve, sep } from 'node:path';

const WIKI_ROOT = resolve(process.cwd(), 'wiki');

function safeResolve(relPath: string): string {
  // Strip leading slashes, normalize separators
  const cleaned = relPath.replace(/^[/\\]+/, '').replaceAll('\\', '/');
  const abs = resolve(WIKI_ROOT, cleaned);
  const rel = relative(WIKI_ROOT, abs);
  if (rel.startsWith('..') || rel.includes(`..${sep}`) || resolve(abs) !== abs) {
    throw new Error(`path '${relPath}' escapes wiki root`);
  }
  return abs;
}

export async function listWikiPages(directory?: string): Promise<string[]> {
  const root = directory ? safeResolve(directory) : WIKI_ROOT;
  const out: string[] = [];

  async function walk(dir: string) {
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const full = join(dir, e.name);
      if (e.isDirectory()) {
        await walk(full);
      } else if (e.isFile() && e.name.endsWith('.md')) {
        out.push(relative(WIKI_ROOT, full).replaceAll(sep, '/'));
      }
    }
  }

  await walk(root);
  out.sort();
  return out;
}

export async function readWikiPage(path: string): Promise<string> {
  const abs = safeResolve(path);
  const s = await stat(abs);
  if (s.isDirectory()) throw new Error(`path '${path}' is a directory; use list_wiki_pages instead`);
  if (s.size > 200_000) throw new Error(`page '${path}' is too large (${s.size} bytes); ask a more specific question`);
  return readFile(abs, 'utf8');
}

export interface WikiHit {
  path: string;
  line: number;
  context: string;
}

/**
 * Naive case-insensitive grep across all wiki pages. Returns up to `limit`
 * hits with three lines of surrounding context. Multi-word queries are
 * AND-ed across the line.
 */
export async function searchWiki(query: string, limit = 30): Promise<WikiHit[]> {
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length >= 2);
  if (terms.length === 0) return [];

  const pages = await listWikiPages();
  const hits: WikiHit[] = [];

  for (const p of pages) {
    let text: string;
    try {
      text = await readFile(safeResolve(p), 'utf8');
    } catch {
      continue;
    }
    const lines = text.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const lower = lines[i].toLowerCase();
      if (terms.every((t) => lower.includes(t))) {
        const before = lines[i - 1] ?? '';
        const after = lines[i + 1] ?? '';
        const context = [before, lines[i], after].filter(Boolean).join('\n');
        hits.push({ path: p, line: i + 1, context });
        if (hits.length >= limit) return hits;
      }
    }
  }
  return hits;
}
