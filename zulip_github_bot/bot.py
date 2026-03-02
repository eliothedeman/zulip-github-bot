#!/usr/bin/env python3
"""Zulip bot that creates GitHub issues from chat messages.

Uses the official zulip_bots handler interface. Run with:

    zulip-run-bot github_issue_bot \
        --config-file ~/.zuliprc \
        --bot-config-file github_issue_bot.conf

Mention the bot with a message like:
    @issuebot make hotfix with most recent changes
    @issuebot repo:acme/backend Fix login bug
    @issuebot label:bug label:urgent Fix the crash on startup
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import github

logger = logging.getLogger("zulip-github-bot")


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------

@dataclass
class ParsedIssue:
    title: str
    body: str = ""
    labels: list[str] = field(default_factory=list)
    repo: str | None = None  # owner/name override, None means use default


def parse_message(text: str) -> ParsedIssue:
    """Parse a chat message into an issue title, body, labels, and repo.

    Supported formats:

    Simple (entire message becomes title):
        make hotfix with most recent changes

    Target a specific repo:
        repo:acme/backend Fix login bug

    Pipe-separated title and body:
        title: Fix login bug | body: Users can't log in after password reset

    Inline labels:
        label:bug label:urgent Fix the crash on startup
    """
    text = text.strip()

    # Extract inline repo specifier like repo:owner/name
    repo: str | None = None
    repo_match = re.search(r"repo:(\S+/\S+)", text)
    if repo_match:
        repo = repo_match.group(1)
        text = text[:repo_match.start()] + text[repo_match.end():]
        text = text.strip()

    # Extract inline labels like label:bug or label:"multi word"
    labels: list[str] = []
    label_pattern = re.compile(r'label:(?:"([^"]+)"|(\S+))')
    for match in label_pattern.finditer(text):
        labels.append(match.group(1) or match.group(2))
    text = label_pattern.sub("", text).strip()

    # Check for pipe-separated title/body format
    if "|" in text:
        parts = text.split("|", maxsplit=1)
        title_part = parts[0].strip()
        body_part = parts[1].strip()

        # Strip optional "title:" / "body:" prefixes
        title_part = re.sub(r"^title:\s*", "", title_part, flags=re.IGNORECASE)
        body_part = re.sub(r"^body:\s*", "", body_part, flags=re.IGNORECASE)

        return ParsedIssue(title=title_part, body=body_part, labels=labels, repo=repo)

    # Simple format: first line is title, rest is body
    lines = text.split("\n", maxsplit=1)
    title = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""

    return ParsedIssue(title=title, body=body, labels=labels, repo=repo)


# ---------------------------------------------------------------------------
# Bot handler (zulip_bots interface)
# ---------------------------------------------------------------------------

HELP_TEXT = """\
**GitHub Issue Bot** — Create issues by mentioning me!

**Usage:**
- `@issuebot <title>` — create an issue in the default repo
- `@issuebot repo:owner/name <title>` — target a specific repo
- `@issuebot <title> | body: <description>` — title with a body
- `@issuebot label:bug label:urgent <title>` — attach labels
- `@issuebot title: Fix it | body: Details here` — explicit fields
- `@issuebot repos` — list available repos
- `@issuebot help` — show this message

Multi-line messages use the first line as the title and the rest as the body.\
"""


class GithubIssueBot:
    """zulip_bots handler that creates GitHub issues."""

    def usage(self) -> str:
        return HELP_TEXT

    def initialize(self, bot_handler: Any) -> None:
        """Called once at startup. Reads config and connects to GitHub."""
        config = bot_handler.get_config_info("github_issue_bot")

        token = config.get("token", "")
        if not token:
            raise KeyError("github_issue_bot.conf must contain 'token' (GitHub PAT)")

        self.default_repo: str = config.get("default_repo", "")
        if not self.default_repo:
            raise KeyError("github_issue_bot.conf must contain 'default_repo' (owner/repo)")

        # Optional: comma-separated list of owner/repo that users are allowed
        # to target. If omitted, any repo the token has access to is allowed.
        allowed = config.get("allowed_repos", "")
        if allowed:
            self.allowed_repos: set[str] | None = {
                r.strip().lower() for r in allowed.split(",") if r.strip()
            }
            self.allowed_repos.add(self.default_repo.lower())
        else:
            self.allowed_repos = None

        self.gh = github.Github(token)
        self._repo_cache: dict[str, github.Repository.Repository] = {}

        logger.info("Default repo: %s", self.default_repo)
        if self.allowed_repos:
            logger.info("Allowed repos: %s", ", ".join(sorted(self.allowed_repos)))

    # ----- message handling ------------------------------------------------

    def handle_message(self, message: dict, bot_handler: Any) -> None:
        content: str = message.get("content", "").strip()

        # Strip the @-mention prefix that Zulip includes in the raw content
        content = re.sub(r"^@\*\*[^*]+\*\*\s*", "", content).strip()

        if not content or content.lower() in ("help", "?"):
            bot_handler.send_reply(message, HELP_TEXT)
            return

        if content.lower() == "repos":
            bot_handler.send_reply(message, self._list_repos())
            return

        parsed = parse_message(content)
        if not parsed.title:
            bot_handler.send_reply(
                message, "I need at least a title to create an issue. Try `help`."
            )
            return

        repo_name = parsed.repo or self.default_repo

        # Check allowlist
        if self.allowed_repos and repo_name.lower() not in self.allowed_repos:
            bot_handler.send_reply(
                message,
                f"`{repo_name}` is not in the allowed repos list. "
                f"Try `repos` to see what's available.",
            )
            return

        try:
            repo = self._get_repo(repo_name)
            issue = self._create_issue(repo, parsed)
        except github.GithubException as exc:
            detail = exc.data.get("message", str(exc)) if isinstance(exc.data, dict) else str(exc)
            bot_handler.send_reply(message, f"Failed to create issue: {detail}")
            return

        response = f"Created issue [#{issue.number}: {issue.title}]({issue.html_url})"
        if repo_name != self.default_repo:
            response += f" in **{repo_name}**"
        if parsed.labels:
            response += f" with labels: {', '.join(f'`{l}`' for l in parsed.labels)}"
        bot_handler.send_reply(message, response)

    # ----- helpers ---------------------------------------------------------

    def _get_repo(self, name: str) -> github.Repository.Repository:
        key = name.lower()
        if key not in self._repo_cache:
            self._repo_cache[key] = self.gh.get_repo(name)
        return self._repo_cache[key]

    @staticmethod
    def _create_issue(
        repo: github.Repository.Repository, parsed: ParsedIssue
    ) -> github.Issue.Issue:
        kwargs: dict = {"title": parsed.title}
        if parsed.body:
            kwargs["body"] = parsed.body
        if parsed.labels:
            kwargs["labels"] = parsed.labels
        return repo.create_issue(**kwargs)

    def _list_repos(self) -> str:
        if self.allowed_repos:
            repos = sorted(self.allowed_repos)
            lines = [f"- `{r}`" + (" *(default)*" if r == self.default_repo.lower() else "") for r in repos]
            return "**Available repos:**\n" + "\n".join(lines)
        return f"Any repo the bot token can access. Default: `{self.default_repo}`"


handler_class = GithubIssueBot
