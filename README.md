# Zulip GitHub Issue Bot

A Zulip bot that creates GitHub issues directly from chat messages.

## Setup

### 1. Create a Zulip bot

In your Zulip organization go to **Settings → Your bots → Add a new bot**. Choose "Generic bot" and download the generated `zuliprc` file to `~/.zuliprc`.

### 2. Create a GitHub token

Create a [personal access token](https://github.com/settings/tokens) with `repo` scope.

### 3. Install and run

```bash
pip install .

# Via environment variables
export GITHUB_TOKEN=ghp_...
export GITHUB_REPO=owner/repo
zulip-github-bot

# Or via CLI flags
zulip-github-bot --github-token ghp_... --github-repo owner/repo --zuliprc ~/.zuliprc
```

## Usage

Mention the bot in any stream or send it a direct message:

| Message | Result |
|---|---|
| `@issuebot make hotfix with most recent changes` | Creates an issue titled "make hotfix with most recent changes" |
| `@issuebot Fix login bug \| body: Users can't log in after reset` | Title + body |
| `@issuebot label:bug label:urgent Fix crash` | Issue with labels `bug` and `urgent` |
| `@issuebot help` | Shows usage instructions |

Multi-line messages use the first line as the title and everything after as the body.

## Configuration

| Source | Variable / Flag | Description |
|---|---|---|
| Env | `GITHUB_TOKEN` | GitHub personal access token |
| Env | `GITHUB_REPO` | Target repo (`owner/repo`) |
| Env | `ZULIP_RC` | Path to zuliprc file |
| CLI | `--github-token` | Same as `GITHUB_TOKEN` |
| CLI | `--github-repo` | Same as `GITHUB_REPO` |
| CLI | `--zuliprc` | Same as `ZULIP_RC` (default `~/.zuliprc`) |
| CLI | `-v` / `--verbose` | Debug logging |
