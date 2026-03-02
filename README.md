# Zulip GitHub Issue Bot

A Zulip bot that creates GitHub issues directly from chat messages. Built on the official [`zulip_bots`](https://github.com/zulip/python-zulip-api) framework.

## Setup

### 1. Create a Zulip bot

In your Zulip organization go to **Settings → Your bots → Add a new bot**. Choose "Generic bot" and download the generated `zuliprc` file to `~/.zuliprc`.

### 2. Create a GitHub token

Create a [personal access token](https://github.com/settings/tokens) with `repo` scope (or fine-grained with Issues read/write on your target repos).

### 3. Configure the bot

Copy `github_issue_bot.conf` and fill in your values:

```ini
[github_issue_bot]
token=ghp_your_token_here
default_repo=myorg/myrepo

# Optional: restrict which repos users can target
#allowed_repos=myorg/myrepo,myorg/frontend,myorg/backend
```

### 4. Install and run

```bash
pip install .

zulip-run-bot zulip_github_bot/bot.py \
    --config-file ~/.zuliprc \
    --bot-config-file github_issue_bot.conf
```

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

## Multi-repo support

By default the bot files issues against `default_repo`. Users can override per-message with `repo:owner/name`. To restrict which repos are available, set `allowed_repos` in the config file — a comma-separated list of `owner/repo` values. The default repo is always implicitly allowed.

## Configuration reference

All settings live in `github_issue_bot.conf` under the `[github_issue_bot]` section:

| Key | Required | Description |
|---|---|---|
| `token` | Yes | GitHub personal access token |
| `default_repo` | Yes | Fallback repo (`owner/repo`) when no `repo:` is specified |
| `allowed_repos` | No | Comma-separated allowlist of `owner/repo` values |
