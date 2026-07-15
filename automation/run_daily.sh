#!/usr/bin/env bash
# Daily Brief — unattended build & publish.
#   fetch sources → claude writes gists/categories → render (dated + index)
#   → regenerate archive → commit & push. GitHub Pages then serves the latest.
#
# Safe to run by hand or from the systemd user timer. data.json is intermediate
# (gitignored); the committed artifacts are index.html, briefs/<date>.html,
# archive.html.
set -uo pipefail

# Resolve repo root (this script lives in <root>/automation/).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Make tools resolvable even under a bare systemd environment.
export PATH="$HOME/.nix-profile/bin:/run/current-system/sw/bin:/usr/bin:/bin:$PATH"

# Mirror the interactive shell's Claude auth (loaded from secrets in .zshrc).
# A systemd service doesn't source your shell, so load it here if present.
[ -f "$HOME/.config/secrets/anthropic_token" ] && \
  export ANTHROPIC_AUTH_TOKEN="$(cat "$HOME/.config/secrets/anthropic_token")"

# Personalized sources (Reddit/Substack/Medium) read their own credentials
# directly from ~/.config/secrets/ via auth.py — reddit_oauth.json, substack_sid,
# reddit_home_rss. No env wiring needed; absent secrets just fall back to the
# generic tiers, so the brief always builds. See README "Personalize from your
# accounts" for how to populate them.

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

DATE="$(date +%F)"
DISP="$(date +'%-d %B %Y')"

log "daily-brief: starting for $DATE"

if ! python3 fetch_sources.py --out data.json; then
  log "fetch failed — aborting"; exit 1
fi

# Gists + categories via the logged-in claude CLI (falls back to defaults on error).
python3 automation/gen_gists.py --data data.json --model "${BRIEF_MODEL:-sonnet}"

# Dated archive copy (lives in briefs/, so root links need ../) and the latest (root).
python3 render_brief.py --data data.json --date "$DISP" --out "briefs/$DATE.html" --root-prefix "../"
python3 render_brief.py --data data.json --date "$DISP" --out "index.html" --root-prefix ""
python3 automation/gen_archive.py

git add -A index.html briefs archive.html
if git diff --cached --quiet; then
  log "no changes to commit (already built today?)"; exit 0
fi
git commit -q -m "brief: $DATE"
if git push -q origin HEAD:main; then
  log "published $DATE → pushed to origin/main"
else
  log "WARNING: commit made but push failed (check credentials/network)"; exit 1
fi
