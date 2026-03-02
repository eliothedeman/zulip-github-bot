#!/usr/bin/env python3
"""zulip_bots handler — for self-hosted long-running deployments.

Run with:

    zulip-run-bot zulip_github_bot/bot.py \
        --config-file ~/.zuliprc \
        --bot-config-file github_issue_bot.conf
"""

from __future__ import annotations

from typing import Any

from .core import HELP_TEXT, IssueCreator


class GithubIssueBot:
    """zulip_bots handler that creates GitHub issues."""

    def usage(self) -> str:
        return HELP_TEXT

    def initialize(self, bot_handler: Any) -> None:
        config = bot_handler.get_config_info("github_issue_bot")

        token = config.get("token", "")
        if not token:
            raise KeyError("github_issue_bot.conf must contain 'token' (GitHub PAT)")

        default_repo = config.get("default_repo", "")
        if not default_repo:
            raise KeyError("github_issue_bot.conf must contain 'default_repo' (owner/repo)")

        allowed = config.get("allowed_repos", "")
        allowed_repos = [r.strip() for r in allowed.split(",") if r.strip()] if allowed else None

        self.creator = IssueCreator(token, default_repo, allowed_repos)

    def handle_message(self, message: dict, bot_handler: Any) -> None:
        reply = self.creator.handle(message.get("content", ""))
        bot_handler.send_reply(message, reply)


handler_class = GithubIssueBot
