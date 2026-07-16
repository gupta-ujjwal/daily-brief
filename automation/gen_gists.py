#!/usr/bin/env python3
"""Headlessly fill each item's gist + category by driving the `claude` CLI.

This is the unattended replacement for the interactive skill's step 2. It feeds a
compact view of data.json to `claude -p` and asks for a strict JSON array of
{i, category, gist}, then merges the result back into data.json. No API key —
it reuses the logged-in Claude Code CLI.

If the model call or parse fails, every item still gets a safe fallback
(category="industry", gist="") so the render step always succeeds.

    python3 automation/gen_gists.py --data data.json --model sonnet
"""
import argparse
import json
import re
import subprocess
import sys

VALID = {"industry", "learning", "products", "personal"}

PROMPT_HEAD = """\
You are writing a daily digest that blends tech with the reader's personal feed.
For EACH item below, produce:
- "gist": one line, <= 25 words — what the discussion is actually arguing about or
  the key takeaway. NOT a restatement of the title. Use the comments/text.
- "category": exactly one of:
  - "industry": business, funding, M&A, layoffs, policy, company/strategy moves,
    notable launches reported as news.
  - "learning": essays, deep-dives, techniques, research, opinion/discussion, new
    capabilities and concepts worth understanding.
  - "products": things to try or adopt — Show HN, repos, frameworks, tools,
    devices, apps, services.
  - "personal": NON-tech, personal-interest or local posts — local city/community,
    cars/watches/hobbies, lifestyle, memes, sports, real estate, personal finance
    chatter. Anything that is not about technology/software/business belongs here.
  Decide tech-vs-personal FIRST: if it isn't about tech/software/business/science,
  it's "personal". Among tech items, choose by reader intent: read-to-know=industry,
  read-to-learn=learning, go-try-it=products.

Return ONLY a JSON array, one object per item, in the SAME order, shaped exactly:
[{"i": <index>, "category": "industry|learning|products|personal", "gist": "..."}]
No prose, no markdown, no code fences.

ITEMS:
"""


def compact(items):
    out = []
    for i, it in enumerate(items):
        entry = {
            "i": i,
            "src": it.get("source_label"),
            "kind": it.get("kind"),
            "title": it.get("title"),
        }
        text = (it.get("text") or "").strip()
        if text:
            entry["text"] = text[:300]
        comments = [c.get("text", "")[:160] for c in (it.get("comments") or [])[:3]]
        if comments:
            entry["comments"] = comments
        out.append(entry)
    return out


def call_claude(prompt, model, timeout):
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "text", "--model", model],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:300]}")
    return proc.stdout


def parse_array(raw):
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip(), flags=re.S)  # strip fences
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in model output")
    return json.loads(s[start:end + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    with open(args.data) as f:
        d = json.load(f)
    items = d.get("items", [])
    if not items:
        print("gen_gists: no items, nothing to do", file=sys.stderr)
        return

    # Safe fallback first, so a later failure still leaves a renderable file.
    for it in items:
        it.setdefault("category", "industry")
        it.setdefault("gist", "")

    prompt = PROMPT_HEAD + json.dumps(compact(items), ensure_ascii=False)
    try:
        rows = parse_array(call_claude(prompt, args.model, args.timeout))
        by_i = {r["i"]: r for r in rows if isinstance(r, dict) and "i" in r}
        filled = 0
        for i, it in enumerate(items):
            r = by_i.get(i)
            if not r:
                continue
            cat = r.get("category")
            it["category"] = cat if cat in VALID else "industry"
            it["gist"] = (r.get("gist") or "").strip()
            filled += 1
        print(f"gen_gists: filled {filled}/{len(items)} items via claude ({args.model})",
              file=sys.stderr)
    except Exception as e:
        print(f"gen_gists: WARNING fell back to defaults — {e}", file=sys.stderr)

    with open(args.data, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
