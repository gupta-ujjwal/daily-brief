#!/usr/bin/env python3
"""Load personal-account credentials for the daily-brief's authenticated sources.

Every public function here is TOTAL: on a missing secret, a malformed file, or a
failed network exchange it returns ``None`` (or an empty result) and never raises
into the fetchers. A ``None`` simply means "this authenticated tier is
unavailable" and the caller in ``fetch_sources.py`` falls through to the next
tier. This is the boundary the plan calls out — auth is effectful and
failure-prone, so it is kept off the critical path and modelled as an explicit
"headers-or-None", not as exceptions threaded through each fetcher.

Secrets live in ``~/.config/secrets/`` (the same directory as ``anthropic_token``),
matching the project's existing convention. Nothing here is committed; the README
documents how to populate each file:

    ~/.config/secrets/reddit_oauth.json   {"client_id","client_secret","refresh_token"}
    ~/.config/secrets/substack_sid        the substack.sid cookie value, one line

The directory can be overridden with ``$BRIEF_SECRETS_DIR`` (used by tests).
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "daily-brief/2.0 (personal tech digest; +https://news.ycombinator.com)"


def secrets_dir():
    override = os.environ.get("BRIEF_SECRETS_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".config", "secrets")


def read_secret(name):
    """Return the stripped contents of a secret file, or None if absent/empty."""
    path = os.path.join(secrets_dir(), name)
    try:
        with open(path, encoding="utf-8") as f:
            val = f.read().strip()
        return val or None
    except OSError:
        return None


def read_json_secret(name):
    """Return a parsed JSON secret dict, or None if absent/unreadable/malformed."""
    raw = read_secret(name)
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except (ValueError, TypeError):
        return None


def _post_form(url, data, headers=None, timeout=20):
    """Minimal POST helper (get() in fetch_sources.py is GET-only). Returns parsed
    JSON dict, or None on any HTTP/network/parse failure — never raises."""
    body = urllib.parse.urlencode(data).encode()
    hdrs = {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, ValueError, OSError) as e:
        print(f"  auth: POST {url} failed: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Reddit — OAuth "script"/installed app with a stored refresh token.
# Exchange the long-lived refresh token for a 1-hour bearer on each run.
# --------------------------------------------------------------------------- #
def reddit_bearer():
    """Return a Reddit OAuth bearer token, or None if unconfigured/failed.

    Reads ~/.config/secrets/reddit_oauth.json with client_id, client_secret and
    refresh_token (mint the refresh_token once via the auth-code flow — see the
    README; password-grant is avoided because it breaks under 2FA)."""
    cfg = read_json_secret("reddit_oauth.json")
    if not cfg:
        return None
    cid = cfg.get("client_id")
    secret = cfg.get("client_secret")
    refresh = cfg.get("refresh_token")
    if not (cid and refresh):
        print("  auth: reddit_oauth.json missing client_id/refresh_token", file=sys.stderr)
        return None
    # HTTP Basic auth with client_id:client_secret; installed apps use an empty secret.
    basic = base64.b64encode(f"{cid}:{secret or ''}".encode()).decode()
    resp = _post_form(
        "https://www.reddit.com/api/v1/access_token",
        {"grant_type": "refresh_token", "refresh_token": refresh},
        headers={"Authorization": f"Basic {basic}"},
    )
    if not resp:
        return None
    token = resp.get("access_token")
    if not token:
        print(f"  auth: reddit token exchange returned no access_token ({resp})", file=sys.stderr)
        return None
    return token


# --------------------------------------------------------------------------- #
# Substack — a single session cookie (substack.sid) authenticates the reader API.
# --------------------------------------------------------------------------- #
def substack_cookie_header():
    """Return a Cookie header value for Substack, or None if the sid isn't set.

    Accepts either a bare sid value or a full `substack.sid=...` string in the
    secret file, and normalizes to a proper Cookie header."""
    sid = read_secret("substack_sid")
    if not sid:
        return None
    if "=" in sid.split(";", 1)[0]:
        return sid  # already a name=value cookie string
    return f"substack.sid={sid}"
