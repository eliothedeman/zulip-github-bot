#!/usr/bin/env python3
"""Flask webhook server — for cloud deployments (Cloud Run, Fly.io, etc.).

Receives Zulip outgoing-webhook POSTs, creates GitHub issues, and returns
a JSON reply that Zulip renders as a bot message.

Configuration is via environment variables:

    GITHUB_TOKEN        GitHub personal access token (required)
    DEFAULT_REPO        owner/repo (required)
    ALLOWED_REPOS       comma-separated owner/repo list (optional)
    ZULIP_WEBHOOK_TOKEN token from the Zulip outgoing-webhook bot (optional, for auth)
    PORT                port to listen on (default 8080)
"""

from __future__ import annotations

import hmac
import logging
import os

from flask import Flask, Response, jsonify, request

from .core import IssueCreator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("zulip-github-bot")

app = Flask(__name__)

# Initialized on first request (not at import time so env vars can be set by
# the container runtime before the first request arrives).
_creator: IssueCreator | None = None


def _get_creator() -> IssueCreator:
    global _creator
    if _creator is None:
        token = os.environ.get("GITHUB_TOKEN", "")
        default_repo = os.environ.get("DEFAULT_REPO", "")
        if not token or not default_repo:
            raise RuntimeError(
                "GITHUB_TOKEN and DEFAULT_REPO environment variables are required"
            )
        allowed = os.environ.get("ALLOWED_REPOS", "")
        allowed_repos = [r.strip() for r in allowed.split(",") if r.strip()] if allowed else None
        _creator = IssueCreator(token, default_repo, allowed_repos)
        logger.info("IssueCreator ready — default repo: %s", default_repo)
    return _creator


@app.post("/webhook")
def webhook() -> tuple[Response, int]:
    """Handle a Zulip outgoing-webhook POST."""
    # Optional: verify the request came from your Zulip server.
    expected_token = os.environ.get("ZULIP_WEBHOOK_TOKEN")
    if expected_token:
        payload_token = request.json.get("token", "") if request.json else ""
        if not hmac.compare_digest(payload_token, expected_token):
            return jsonify({"error": "invalid token"}), 403

    data = request.json or {}
    message = data.get("message", {})
    content = message.get("content", data.get("data", ""))

    creator = _get_creator()
    reply = creator.handle(content)

    # Zulip expects {"content": "..."} in the response body.
    return jsonify({"content": reply}), 200


@app.get("/healthz")
def health() -> tuple[Response, int]:
    return jsonify({"status": "ok"}), 200


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
