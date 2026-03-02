FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY zulip_github_bot/ zulip_github_bot/

RUN pip install --no-cache-dir '.[webhook]'

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "zulip_github_bot.webhook:app"]
