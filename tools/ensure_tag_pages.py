#!/usr/bin/env python3
"""ensure_tag_pages.py — give every tag an indexable landing page.

Scans _posts/ for `tags:` in front matter and creates a stub `tag/<slug>.md`
for any tag that doesn't already have one. Idempotent: only adds files, never
edits or deletes, so hand-curated intros are preserved. Stdlib only.

`new_entry.py` calls this after writing a post and before `git add`, so a brand
new tag gets its landing page in the same commit.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "_posts"
TAGDIR = ROOT / "tag"

TAGS_RE = re.compile(r"^tags:\s*\[(.*?)\]", re.MULTILINE)


def slugify(tag):
    return re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")


def collect_tags():
    tags = set()
    for post in POSTS.glob("*.md"):
        text = post.read_text(encoding="utf-8")
        m = TAGS_RE.search(text)
        if m:
            for t in m.group(1).split(","):
                t = t.strip().strip('"').strip("'")
                if t:
                    tags.add(t)
    return sorted(tags)


def main():
    TAGDIR.mkdir(exist_ok=True)
    created = []
    for tag in collect_tags():
        slug = slugify(tag)
        dest = TAGDIR / f"{slug}.md"
        if dest.exists():
            continue
        dest.write_text(
            "---\n"
            "layout: tag\n"
            f'title: "Tagged: {tag}"\n'
            f"tag: {tag}\n"
            f"permalink: /tag/{slug}/\n"
            f'description: "Every Vega entry tagged {tag}."\n'
            "---\n",
            encoding="utf-8",
        )
        created.append(slug)
    print(f"created tag pages: {', '.join(created)}" if created
          else "All tag pages already exist.")


if __name__ == "__main__":
    main()
