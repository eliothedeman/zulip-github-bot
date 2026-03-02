#!/usr/bin/env python3
"""Zulip bot that creates GitHub issues from chat messages.

Mention the bot with a message like:
    @issuebot make hotfix with most recent changes
    @issuebot title: Fix login bug | body: Users can't log in after password reset
    @issuebot label:bug label:urgent Fix the crash on startup
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass, field

import github
import zulip

logger = logging.getLogger("zulip-github-bot")


@dataclass
class ParsedIssue:
    title: str
    body: str = ""
    labels: list[str] = field(default_factory=list)


def parse_message(text: str) -> ParsedIssue:
    """Parse a chat message into an issue title, body, and labels.

    Supports several formats:

    Simple (entire message becomes title):
        make hotfix with most recent changes

    Pipe-separated title and body:
        title: Fix login bug | body: Users can't log in after password reset

    Inline labels:
        label:bug label:urgent Fix the crash on startup
    """
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

        return ParsedIssue(title=title_part, body=body_part, labels=labels)

    # Simple format: first line is title, rest is body
    lines = text.split("\n", maxsplit=1)
    title = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""

    return ParsedIssue(title=title, body=body, labels=labels)


class IssueBotHandler:
    """Zulip bot handler that creates GitHub issues."""

    HELP_TEXT = """\
**GitHub Issue Bot** — Create issues by mentioning me!

**Usage:**
- `@issuebot <title>` — create an issue with the given title
- `@issuebot <title> | body: <description>` — title with a body
- `@issuebot label:bug label:urgent <title>` — attach labels
- `@issuebot title: Fix it | body: Details here` — explicit fields
- `@issuebot help` — show this message

Multi-line messages use the first line as the title and the rest as the body.\
"""

    def __init__(self, github_token: str, github_repo: str) -> None:
        self.gh = github.Github(github_token)
        self.repo = self.gh.get_repo(github_repo)
        logger.info("Connected to GitHub repo: %s", self.repo.full_name)

    def handle_message(self, message: dict, bot_client: zulip.Client) -> None:
        """Process an incoming Zulip message and maybe create a GitHub issue."""
        content: str = message.get("content", "").strip()

        # The Zulip API delivers the raw message content. When the bot is
        # mentioned the message looks like `@**BotName** <rest>`. Strip the
        # mention prefix so we can work with the user's actual text.
        content = re.sub(r"^@\*\*[^*]+\*\*\s*", "", content).strip()

        if not content or content.lower() in ("help", "?"):
            self._reply(bot_client, message, self.HELP_TEXT)
            return

        parsed = parse_message(content)
        if not parsed.title:
            self._reply(bot_client, message, "I need at least a title to create an issue. Try `@issuebot help`.")
            return

        try:
            issue = self._create_issue(parsed)
        except github.GithubException as exc:
            logger.exception("GitHub API error")
            self._reply(bot_client, message, f"Failed to create issue: {exc.data.get('message', str(exc))}")
            return

        response = f"Created issue [#{issue.number}: {issue.title}]({issue.html_url})"
        if parsed.labels:
            response += f" with labels: {', '.join(f'`{l}`' for l in parsed.labels)}"
        self._reply(bot_client, message, response)

    def _create_issue(self, parsed: ParsedIssue) -> github.Issue.Issue:
        kwargs: dict = {"title": parsed.title}
        if parsed.body:
            kwargs["body"] = parsed.body
        if parsed.labels:
            kwargs["labels"] = parsed.labels
        return self.repo.create_issue(**kwargs)

    @staticmethod
    def _reply(client: zulip.Client, original: dict, content: str) -> None:
        """Send a reply in the same stream/topic or PM thread."""
        if original["type"] == "stream":
            client.send_message({
                "type": "stream",
                "to": original["display_recipient"],
                "topic": original.get("subject", ""),
                "content": content,
            })
        else:
            client.send_message({
                "type": "private",
                "to": [r["email"] for r in original["display_recipient"]],
                "content": content,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="Zulip bot that creates GitHub issues")
    parser.add_argument("--zuliprc", default=os.environ.get("ZULIP_RC", "~/.zuliprc"),
                        help="Path to the Zulip bot config file (default: ~/.zuliprc or $ZULIP_RC)")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"),
                        help="GitHub personal access token (or set $GITHUB_TOKEN)")
    parser.add_argument("--github-repo", default=os.environ.get("GITHUB_REPO"),
                        help="GitHub repo in owner/name format (or set $GITHUB_REPO)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not args.github_token:
        sys.exit("Error: provide --github-token or set $GITHUB_TOKEN")
    if not args.github_repo:
        sys.exit("Error: provide --github-repo or set $GITHUB_REPO (e.g. owner/repo)")

    zulip_client = zulip.Client(config_file=os.path.expanduser(args.zuliprc))
    handler = IssueBotHandler(args.github_token, args.github_repo)

    logger.info("Registering event queue…")
    result = zulip_client.register(event_types=["message"])
    queue_id = result["queue_id"]
    last_event_id = result["last_event_id"]

    bot_user_id = zulip_client.get_profile()["user_id"]
    logger.info("Bot user ID: %d — listening for messages…", bot_user_id)

    try:
        while True:
            events = zulip_client.get_events(
                queue_id=queue_id, last_event_id=last_event_id, dont_block=False,
            )
            for event in events.get("events", []):
                last_event_id = max(last_event_id, event["id"])
                if event["type"] != "message":
                    continue
                msg = event["message"]
                # Ignore messages sent by the bot itself
                if msg["sender_id"] == bot_user_id:
                    continue
                # Only respond when the bot is mentioned or in a PM
                is_mentioned = any(
                    m.get("id") == bot_user_id for m in msg.get("mentions", [])
                )
                is_pm = msg["type"] == "private"
                if is_mentioned or is_pm:
                    handler.handle_message(msg, zulip_client)
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
