"""Shared parsing and GitHub logic used by both the zulip_bots handler and the
webhook server."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import github


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


class IssueCreator:
    """Thin wrapper around the GitHub API for creating issues."""

    def __init__(
        self,
        github_token: str,
        default_repo: str,
        allowed_repos: list[str] | None = None,
    ) -> None:
        self.gh = github.Github(github_token)
        self.default_repo = default_repo

        self.allowed_repos: set[str] | None = None
        if allowed_repos:
            self.allowed_repos = {r.strip().lower() for r in allowed_repos}
            self.allowed_repos.add(default_repo.lower())

        self._repo_cache: dict[str, github.Repository.Repository] = {}

    def handle(self, raw_content: str) -> str:
        """Process raw message text and return a Markdown response string."""
        content = re.sub(r"^@\*\*[^*]+\*\*\s*", "", raw_content).strip()

        if not content or content.lower() in ("help", "?"):
            return HELP_TEXT

        if content.lower() == "repos":
            return self._list_repos()

        parsed = parse_message(content)
        if not parsed.title:
            return "I need at least a title to create an issue. Try `help`."

        repo_name = parsed.repo or self.default_repo

        if self.allowed_repos and repo_name.lower() not in self.allowed_repos:
            return (
                f"`{repo_name}` is not in the allowed repos list. "
                f"Try `repos` to see what's available."
            )

        try:
            repo = self._get_repo(repo_name)
            issue = self._create_issue(repo, parsed)
        except github.GithubException as exc:
            detail = exc.data.get("message", str(exc)) if isinstance(exc.data, dict) else str(exc)
            return f"Failed to create issue: {detail}"

        response = f"Created issue [#{issue.number}: {issue.title}]({issue.html_url})"
        if repo_name != self.default_repo:
            response += f" in **{repo_name}**"
        if parsed.labels:
            response += f" with labels: {', '.join(f'`{l}`' for l in parsed.labels)}"
        return response

    # -- internal -----------------------------------------------------------

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
            lines = [
                f"- `{r}`" + (" *(default)*" if r == self.default_repo.lower() else "")
                for r in repos
            ]
            return "**Available repos:**\n" + "\n".join(lines)
        return f"Any repo the bot token can access. Default: `{self.default_repo}`"
