/**
 * Zulip GitHub Issue Bot — Cloudflare Worker
 *
 * Receives Zulip outgoing-webhook POSTs, creates GitHub issues, and returns
 * a JSON reply that Zulip renders as a bot message.
 *
 * Secrets (set via `wrangler secret put`):
 *   GITHUB_TOKEN          GitHub personal access token
 *   ZULIP_WEBHOOK_TOKEN   (optional) validates requests came from your Zulip
 *
 * Env vars (set in wrangler.toml [vars]):
 *   DEFAULT_REPO          owner/repo
 *   ALLOWED_REPOS         comma-separated owner/repo list (optional)
 */

export interface Env {
  GITHUB_TOKEN: string;
  DEFAULT_REPO: string;
  ALLOWED_REPOS?: string;
  ZULIP_WEBHOOK_TOKEN?: string;
}

// ── Message parsing ─────────────────────────────────────────────────────

interface ParsedIssue {
  title: string;
  body: string;
  labels: string[];
  repo: string | null;
}

function parseMessage(text: string): ParsedIssue {
  text = text.trim();

  // Extract inline repo: specifier
  let repo: string | null = null;
  const repoMatch = text.match(/repo:(\S+\/\S+)/);
  if (repoMatch) {
    repo = repoMatch[1]!;
    text = (text.slice(0, repoMatch.index) + text.slice(repoMatch.index! + repoMatch[0].length)).trim();
  }

  // Extract inline labels
  const labels: string[] = [];
  const labelRe = /label:(?:"([^"]+)"|(\S+))/g;
  let m: RegExpExecArray | null;
  while ((m = labelRe.exec(text)) !== null) {
    labels.push((m[1] ?? m[2])!);
  }
  text = text.replace(labelRe, "").trim();

  // Pipe-separated title | body
  if (text.includes("|")) {
    const [rawTitle = "", rawBody = ""] = text.split("|", 2);
    const title = rawTitle.trim().replace(/^title:\s*/i, "");
    const body = rawBody.trim().replace(/^body:\s*/i, "");
    return { title, body, labels, repo };
  }

  // Simple: first line is title, rest is body
  const [first = "", ...rest] = text.split("\n");
  return {
    title: first.trim(),
    body: rest.join("\n").trim(),
    labels,
    repo,
  };
}

// ── GitHub API ──────────────────────────────────────────────────────────

interface GitHubIssueResponse {
  number: number;
  title: string;
  html_url: string;
}

async function createGitHubIssue(
  token: string,
  repoFullName: string,
  parsed: ParsedIssue,
): Promise<GitHubIssueResponse> {
  const body: Record<string, unknown> = { title: parsed.title };
  if (parsed.body) body.body = parsed.body;
  if (parsed.labels.length > 0) body.labels = parsed.labels;

  const res = await fetch(
    `https://api.github.com/repos/${repoFullName}/issues`,
    {
      method: "POST",
      headers: {
        Authorization: `token ${token}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "zulip-github-bot-worker",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    },
  );

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    throw new Error((err.message as string) ?? `GitHub API ${res.status}`);
  }

  return res.json() as Promise<GitHubIssueResponse>;
}

// ── Help text ───────────────────────────────────────────────────────────

const HELP_TEXT = `\
**GitHub Issue Bot** — Create issues by mentioning me!

**Usage:**
- \`@issuebot <title>\` — create an issue in the default repo
- \`@issuebot repo:owner/name <title>\` — target a specific repo
- \`@issuebot <title> | body: <description>\` — title with a body
- \`@issuebot label:bug label:urgent <title>\` — attach labels
- \`@issuebot title: Fix it | body: Details here\` — explicit fields
- \`@issuebot repos\` — list available repos
- \`@issuebot help\` — show this message

Multi-line messages use the first line as the title and the rest as the body.`;

// ── Request handler ─────────────────────────────────────────────────────

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  const enc = new TextEncoder();
  const bufA = enc.encode(a);
  const bufB = enc.encode(b);
  // constant-time comparison via crypto.subtle isn't available in Workers for
  // raw strings, so we do a simple xor-accumulate which is still constant-time.
  let diff = 0;
  for (let i = 0; i < bufA.length; i++) {
    diff |= bufA[i]! ^ bufB[i]!;
  }
  return diff === 0;
}

function allowedReposSet(env: Env): Set<string> | null {
  const raw = env.ALLOWED_REPOS?.trim();
  if (!raw) return null;
  const set = new Set(raw.split(",").map((r) => r.trim().toLowerCase()).filter(Boolean));
  set.add(env.DEFAULT_REPO.toLowerCase());
  return set;
}

function listRepos(env: Env): string {
  const allowed = allowedReposSet(env);
  if (allowed) {
    const lines = [...allowed]
      .sort()
      .map((r) => `- \`${r}\`${r === env.DEFAULT_REPO.toLowerCase() ? " *(default)*" : ""}`);
    return "**Available repos:**\n" + lines.join("\n");
  }
  return `Any repo the bot token can access. Default: \`${env.DEFAULT_REPO}\``;
}

async function handleWebhook(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const data = (await request.json().catch(() => ({}))) as Record<string, unknown>;

  // Optional token validation
  if (env.ZULIP_WEBHOOK_TOKEN) {
    const payloadToken = (data.token as string) ?? "";
    if (!timingSafeEqual(payloadToken, env.ZULIP_WEBHOOK_TOKEN)) {
      return Response.json({ error: "invalid token" }, { status: 403 });
    }
  }

  const message = (data.message ?? {}) as Record<string, unknown>;
  let content = ((message.content as string) ?? (data.data as string) ?? "").trim();

  // Strip @-mention prefix
  content = content.replace(/^@\*\*[^*]+\*\*\s*/, "").trim();

  if (!content || content.toLowerCase() === "help" || content === "?") {
    return Response.json({ content: HELP_TEXT });
  }

  if (content.toLowerCase() === "repos") {
    return Response.json({ content: listRepos(env) });
  }

  const parsed = parseMessage(content);
  if (!parsed.title) {
    return Response.json({ content: "I need at least a title to create an issue. Try `help`." });
  }

  const repoName = parsed.repo ?? env.DEFAULT_REPO;

  const allowed = allowedReposSet(env);
  if (allowed && !allowed.has(repoName.toLowerCase())) {
    return Response.json({
      content: `\`${repoName}\` is not in the allowed repos list. Try \`repos\` to see what's available.`,
    });
  }

  try {
    const issue = await createGitHubIssue(env.GITHUB_TOKEN, repoName, parsed);
    let reply = `Created issue [#${issue.number}: ${issue.title}](${issue.html_url})`;
    if (repoName !== env.DEFAULT_REPO) reply += ` in **${repoName}**`;
    if (parsed.labels.length > 0) {
      reply += ` with labels: ${parsed.labels.map((l) => `\`${l}\``).join(", ")}`;
    }
    return Response.json({ content: reply });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ content: `Failed to create issue: ${msg}` });
  }
}

// ── Worker entry point ──────────────────────────────────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/webhook") {
      return handleWebhook(request, env);
    }

    if (url.pathname === "/healthz") {
      return Response.json({ status: "ok" });
    }

    return new Response("Not found", { status: 404 });
  },
} satisfies ExportedHandler<Env>;
