#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SUBMIT_URL = "https://oauth.reddit.com/api/submit"
SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")


def fail(message: str) -> None:
    raise SystemExit(message)


def read_body(path: str) -> str:
    body = Path(path).read_text(encoding="utf-8").strip()
    if not body:
        fail("Manifest body is empty.")
    return body


def validate(title: str, body: str, subreddit: str) -> None:
    if not title.strip():
        fail("Reddit title is empty.")
    if len(title) > 300:
        fail(f"Reddit title is too long ({len(title)} > 300).")
    if not SUBREDDIT_RE.fullmatch(subreddit):
        fail("Invalid subreddit name.")
    for required in (
        "https://neo-collettive.onrender.com/.well-known/agent-card.json",
        "https://neo-collettive.onrender.com/a2a",
        "https://github.com/Toramo747/Neo-collettive",
    ):
        if required not in body:
            fail(f"Manifest is missing required URL: {required}")


def post_form(url: str, fields: dict[str, str], headers: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        fail(f"Reddit HTTP {exc.code}: {raw[:1000]}")
    except urllib.error.URLError as exc:
        fail(f"Reddit network error: {exc.reason}")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"Reddit returned non-JSON data: {raw[:1000]}")

    if not isinstance(parsed, dict):
        fail("Reddit returned an unexpected response type.")
    return parsed


def get_access_token(client_id: str, client_secret: str, refresh_token: str, user_agent: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    result = post_form(
        TOKEN_URL,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        {
            "Authorization": f"Basic {basic}",
            "User-Agent": user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    token = str(result.get("access_token") or "").strip()
    if not token:
        fail("Could not obtain Reddit access token.")
    return token


def publish(title: str, body: str, subreddit: str) -> str:
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("REDDIT_REFRESH_TOKEN", "").strip()

    missing = [
        name for name, value in (
            ("REDDIT_CLIENT_ID", client_id),
            ("REDDIT_CLIENT_SECRET", client_secret),
            ("REDDIT_REFRESH_TOKEN", refresh_token),
        )
        if not value
    ]
    if missing:
        fail("Missing GitHub Secrets: " + ", ".join(missing))

    user_agent = os.getenv(
        "REDDIT_USER_AGENT",
        "script:mycelix-reddit-publisher:v1.0 (GitHub Actions)",
    ).strip()

    token = get_access_token(client_id, client_secret, refresh_token, user_agent)

    result = post_form(
        SUBMIT_URL,
        {
            "api_type": "json",
            "kind": "self",
            "sr": subreddit,
            "title": title,
            "text": body,
            "resubmit": "true",
            "sendreplies": "true",
            "raw_json": "1",
        },
        {
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    json_part = result.get("json") if isinstance(result.get("json"), dict) else {}
    errors = json_part.get("errors") if isinstance(json_part, dict) else None
    if errors:
        fail("Reddit rejected the post: " + json.dumps(errors)[:2000])

    data = json_part.get("data") if isinstance(json_part, dict) else {}
    if not isinstance(data, dict):
        data = {}

    post_url = str(data.get("url") or "").strip()
    post_id = str(data.get("id") or "").strip()
    if not post_url and post_id:
        post_url = f"https://www.reddit.com/comments/{post_id}/"
    if not post_url:
        fail("Reddit reported no error but did not return a post URL.")

    print(f"POST_URL={post_url}")
    return post_url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("validate", "publish"), default="validate")
    parser.add_argument("--subreddit", default="AI_Agents")
    parser.add_argument(
        "--title",
        default="MYCELIX — An Open Experiment in Agent-to-Agent Collective Intelligence",
    )
    parser.add_argument("--body-file", default="docs/reddit_manifest.md")
    args = parser.parse_args()

    body = read_body(args.body_file)
    validate(args.title, body, args.subreddit)
    print(
        f"Validated Reddit post: r/{args.subreddit}, "
        f"title_chars={len(args.title)}, body_chars={len(body)}"
    )

    if args.mode == "publish":
        publish(args.title, body, args.subreddit)


if __name__ == "__main__":
    main()
