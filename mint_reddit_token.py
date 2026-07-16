#!/usr/bin/env python3
"""One-time helper: mint a Reddit OAuth **refresh token** for the daily-brief.

The daily brief reads your personalized home feed via `GET /best` using a stored
refresh token (chosen over password-grant so 2FA doesn't break it). Getting that
refresh token needs a one-time browser "allow" click — this script runs the whole
authorization-code flow locally: it opens your browser, catches Reddit's redirect
on http://localhost:8080, exchanges the code, and writes
~/.config/secrets/reddit_oauth.json.

Prereq — create the app first at https://www.reddit.com/prefs/apps
  • type:         script
  • redirect uri: http://localhost:8080   (must match exactly)
Then note the client_id (the string just under the app name) and the secret.

Run:  python3 mint_reddit_token.py
"""
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

REDIRECT = "http://localhost:8080"
PORT = 8080
SCOPES = "read mysubreddits"
UA = "daily-brief/2.0 (token setup; by /u/)"
OUT = os.path.join(os.path.expanduser("~"), ".config", "secrets", "reddit_oauth.json")

_result = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _result.update({k: v[0] for k, v in params.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = "code" in _result and "error" not in _result
        msg = "Authorized — you can close this tab and return to the terminal." if ok \
            else f"Authorization failed: {_result.get('error', 'unknown')}"
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode())

    def log_message(self, *a):  # silence the default request logging
        pass


def _post_token(client_id, client_secret, data):
    import base64
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=body,
        headers={"Authorization": f"Basic {basic}", "User-Agent": UA},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def main():
    print("Reddit app credentials (from https://www.reddit.com/prefs/apps):")
    client_id = input("  client_id: ").strip()
    client_secret = input("  client_secret: ").strip()
    if not client_id:
        sys.exit("client_id is required")

    state = secrets.token_urlsafe(16)
    auth_url = "https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "state": state,
        "redirect_uri": REDIRECT, "duration": "permanent", "scope": SCOPES,
    })

    print(f"\nOpening your browser to authorize (scopes: {SCOPES})…")
    print(f"If it doesn't open, paste this URL manually:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print(f"Waiting for the redirect on {REDIRECT} …")
    server = http.server.HTTPServer(("localhost", PORT), _Handler)
    server.handle_request()  # blocks until Reddit redirects back once

    if _result.get("state") != state:
        sys.exit("state mismatch — aborting (possible CSRF); re-run.")
    if "code" not in _result:
        sys.exit(f"no auth code returned: {_result}")

    print("Exchanging code for tokens…")
    tok = _post_token(client_id, client_secret, {
        "grant_type": "authorization_code", "code": _result["code"],
        "redirect_uri": REDIRECT,
    })
    refresh = tok.get("refresh_token")
    if not refresh:
        sys.exit(f"no refresh_token in response: {tok}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"client_id": client_id, "client_secret": client_secret,
                   "refresh_token": refresh}, f, indent=2)
    os.chmod(OUT, 0o600)
    print(f"\n✓ Wrote {OUT} (chmod 600). Reddit personalization is ready.")
    print("  Verify with:  python3 fetch_sources.py --out data.json  "
          "(look for reddit 'served by tier home-oauth')")


if __name__ == "__main__":
    main()
