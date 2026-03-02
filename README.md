# Zulip GitHub Issue Bot

A Zulip bot that creates GitHub issues directly from chat messages. Three deployment modes:

- **Cloudflare Workers** — zero-config edge deployment (TypeScript)
- **Docker / Cloud Run / Fly.io** — containerized Python webhook server
- **Self-hosted** — long-running process using [`zulip_bots`](https://github.com/zulip/python-zulip-api)

## Usage

Mention the bot in any stream or send it a direct message:

| Message | Result |
|---|---|
| `@issuebot make hotfix with most recent changes` | Issue in the default repo |
| `@issuebot repo:acme/backend Fix login bug` | Issue in a specific repo |
| `@issuebot Fix bug \| body: Users can't log in` | Title + body |
| `@issuebot label:bug label:urgent Fix crash` | Issue with labels |
| `@issuebot repos` | List available repos |
| `@issuebot help` | Show usage instructions |

Multi-line messages use the first line as the title and everything after as the body.

---

## Zulip setup (all modes)

1. In your Zulip organization: **Settings → Your bots → Add a new bot**
2. Choose **Outgoing webhook** (for cloud deploys) or **Generic bot** (for self-hosted)
3. For outgoing webhooks, set the endpoint URL to `https://<your-domain>/webhook` and note the **webhook token**
4. Create a [GitHub personal access token](https://github.com/settings/tokens) with `repo` scope

---

## Deploy to Cloudflare Workers

The fastest path — no containers, no servers. The Worker lives in `worker/`.

```bash
cd worker
npm install

# Set your repo in wrangler.toml [vars]:
#   DEFAULT_REPO = "myorg/myrepo"
#   ALLOWED_REPOS = "myorg/myrepo,myorg/frontend"  # optional

# Store secrets:
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put ZULIP_WEBHOOK_TOKEN   # optional

# Deploy:
npm run deploy
```

Wrangler will print the Worker URL. Set `<worker-url>/webhook` as the endpoint in your Zulip outgoing-webhook bot.

To develop locally: `npm run dev`, then POST to `http://localhost:8787/webhook`.

---

## Deploy with Docker / Cloud Run / Fly.io

A Python Flask webhook server with a Dockerfile. Zulip sends HTTP requests to your server whenever the bot is mentioned.

### GCP Cloud Run (one command)

```bash
# From the repo root:
gcloud run deploy zulip-github-bot \
    --source . \
    --set-env-vars GITHUB_TOKEN=ghp_...,DEFAULT_REPO=myorg/myrepo,ZULIP_WEBHOOK_TOKEN=your_zulip_token \
    --allow-unauthenticated \
    --region us-central1
```

Cloud Run will build the Dockerfile, push the image, and give you a URL.
Set that URL + `/webhook` as the endpoint in your Zulip outgoing-webhook bot.

### Fly.io

```bash
fly launch --no-deploy
fly secrets set GITHUB_TOKEN=ghp_... DEFAULT_REPO=myorg/myrepo ZULIP_WEBHOOK_TOKEN=your_zulip_token
fly deploy
```

### Docker (anywhere)

```bash
docker build -t zulip-github-bot .
docker run -p 8080:8080 \
    -e GITHUB_TOKEN=ghp_... \
    -e DEFAULT_REPO=myorg/myrepo \
    -e ZULIP_WEBHOOK_TOKEN=your_zulip_token \
    zulip-github-bot
```

### Environment variables (Docker / Cloud Run / Fly.io)

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | Yes | GitHub personal access token |
| `DEFAULT_REPO` | Yes | Fallback repo (`owner/repo`) |
| `ALLOWED_REPOS` | No | Comma-separated allowlist of `owner/repo` |
| `ZULIP_WEBHOOK_TOKEN` | No | Token from the Zulip outgoing-webhook bot for request validation |
| `PORT` | No | Listen port (default `8080`) |

---

## Self-hosted (zulip_bots mode)

Run the bot as a long-running process on your own server. Zulip's `zulip_bots` framework handles the event polling.

### 1. Create a Zulip generic bot

**Settings → Your bots → Add a new bot** → **Generic bot**. Download the `zuliprc` file.

### 2. Configure

```ini
# github_issue_bot.conf
[github_issue_bot]
token=ghp_your_token_here
default_repo=myorg/myrepo
#allowed_repos=myorg/myrepo,myorg/frontend
```

### 3. Run

```bash
pip install '.[selfhost]'

zulip-run-bot zulip_github_bot/bot.py \
    --config-file ~/.zuliprc \
    --bot-config-file github_issue_bot.conf
```

---

## Multi-repo support

By default the bot files issues against the configured default repo. Users can override per-message with `repo:owner/name`.

To restrict which repos are available, set `ALLOWED_REPOS` (webhook) or `allowed_repos` in the conf file (self-hosted). The default repo is always implicitly allowed.
