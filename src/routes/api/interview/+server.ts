import type { RequestHandler } from './$types';
import Anthropic from '@anthropic-ai/sdk';
import { listWikiPages, readWikiPage, searchWiki } from '$lib/server/wiki';
import { loadSystemPrompt } from '$lib/server/system_prompt';

// Default to Sonnet 4.6 for cost/latency; override with INTERVIEWER_MODEL env var
// to run on Opus 4.7 (more thoughtful but slower & more expensive).
const MODEL = process.env.INTERVIEWER_MODEL || 'claude-sonnet-4-6';
// Hard caps so a runaway interview can't burn the budget.
const MAX_TOOL_TURNS = 12;
const MAX_TOKENS_PER_TURN = 1500;

// Neutralize attempts to break out of the <participant> wrapper. We simply
// strip any literal <participant> or </participant> tags from user content;
// the wrapper we add ourselves is the only one the model should see.
function sanitizeUserContent(s: string): string {
  return s.replace(/<\/?participant\s*\/?>/gi, '');
}

const tools: Anthropic.Messages.Tool[] = [
  {
    name: 'list_wiki_pages',
    description:
      "List all markdown pages in the wiki. Optionally scope to a sub-directory like 'projects' or 'members' or 'channels'.",
    input_schema: {
      type: 'object',
      properties: {
        directory: {
          type: 'string',
          description: "Optional sub-directory inside wiki/, e.g. 'projects' or 'members/'."
        }
      }
    }
  },
  {
    name: 'search_wiki',
    description:
      'Search the wiki for a query. Returns up to 30 matching lines with context. Multi-word queries are AND-ed.',
    input_schema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'The search query. Use 2+ words for tighter results.'
        }
      },
      required: ['query']
    }
  },
  {
    name: 'read_wiki_page',
    description:
      "Read the full text of a wiki page. The path must be inside wiki/, e.g. 'overview.md' or 'projects/magazine.md'.",
    input_schema: {
      type: 'object',
      properties: {
        path: {
          type: 'string',
          description: "Path to the page relative to wiki/, e.g. 'projects/magazine.md'."
        }
      },
      required: ['path']
    }
  }
];

interface ClientMessage {
  role: 'user' | 'assistant';
  content: string;
}

async function runTool(name: string, input: Record<string, unknown>): Promise<string> {
  try {
    if (name === 'list_wiki_pages') {
      const pages = await listWikiPages(typeof input.directory === 'string' ? input.directory : undefined);
      return pages.join('\n');
    }
    if (name === 'search_wiki') {
      const q = String(input.query ?? '');
      const hits = await searchWiki(q);
      if (hits.length === 0) return `No matches for: ${q}`;
      return hits
        .map((h) => `=== ${h.path}:${h.line} ===\n${h.context}`)
        .join('\n\n');
    }
    if (name === 'read_wiki_page') {
      return await readWikiPage(String(input.path ?? ''));
    }
    return `Unknown tool: ${name}`;
  } catch (e) {
    return `tool error: ${(e as Error).message}`;
  }
}

export const POST: RequestHandler = async ({ request }) => {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return new Response('ANTHROPIC_API_KEY not set', { status: 500 });
  }

  const { messages: clientMessages } = (await request.json()) as { messages: ClientMessage[] };
  const systemPrompt = await loadSystemPrompt();
  const client = new Anthropic({ apiKey });

  // Wrap each user message in <participant> tags so it reads as data-about-a-person
  // rather than as instructions. This is the prompt-injection defense the system
  // prompt also points at.
  const apiMessages: Anthropic.Messages.MessageParam[] = clientMessages.map((m) => ({
    role: m.role,
    content:
      m.role === 'user'
        ? [
            {
              type: 'text',
              text: `<participant>\n${sanitizeUserContent(m.content)}\n</participant>`
            } as const
          ]
        : m.content
  }));

  const stream = new ReadableStream({
    async start(controller) {
      const enc = new TextEncoder();
      const send = (event: string, data: unknown) => {
        controller.enqueue(enc.encode(`data: ${JSON.stringify({ event, data })}\n\n`));
      };

      try {
        for (let turn = 0; turn < MAX_TOOL_TURNS; turn++) {
          const response = await client.messages.create({
            model: MODEL,
            max_tokens: MAX_TOKENS_PER_TURN,
            system: [
              {
                type: 'text',
                text: systemPrompt,
                cache_control: { type: 'ephemeral' }
              }
            ],
            tools,
            messages: apiMessages
          });

          // Stream text blocks to the client; collect tool uses for the next turn.
          const toolUses: Array<{ id: string; name: string; input: Record<string, unknown> }> = [];
          for (const block of response.content) {
            if (block.type === 'text') {
              send('text', block.text);
            } else if (block.type === 'tool_use') {
              toolUses.push({
                id: block.id,
                name: block.name,
                input: (block.input as Record<string, unknown>) ?? {}
              });
              send('tool_use', { name: block.name, input: block.input });
            }
          }

          // If no tool was used, this is the final assistant turn.
          if (toolUses.length === 0) {
            break;
          }

          // Append the assistant turn and the tool results, then loop.
          apiMessages.push({ role: 'assistant', content: response.content });
          const toolResults: Anthropic.Messages.ToolResultBlockParam[] = [];
          for (const tu of toolUses) {
            const result = await runTool(tu.name, tu.input);
            toolResults.push({
              type: 'tool_result',
              tool_use_id: tu.id,
              content: result.slice(0, 50_000) // safety cap
            });
          }
          apiMessages.push({ role: 'user', content: toolResults });

          // Stop reason guard
          if (response.stop_reason !== 'tool_use') break;
        }
        send('done', null);
      } catch (e) {
        send('error', (e as Error).message);
      } finally {
        controller.close();
      }
    }
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive'
    }
  });
};
