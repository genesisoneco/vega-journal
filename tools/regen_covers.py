#!/usr/bin/env python3
"""regen_covers.py - rebuild cover SVGs for all existing posts.

Run after changing make_cover() in new_entry.py so older entries pick up the new
cover design. Uses each post's own front matter (mood, tape, spark) and its date.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import new_entry as ne  # noqa: E402


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    posts = sorted(ne.POSTS.glob("*.md"))
    if not posts:
        sys.exit("[error] no posts found.")
    for f in posts:
        fm, _ = ne.split_front_matter(f.read_text(encoding="utf-8"))
        if not fm:
            print(f"[skip] {f.name} (no front matter)")
            continue
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(.+)\.md$", f.name)
        if not m:
            print(f"[skip] {f.name} (unexpected name)")
            continue
        slug = m.group(4)  # filename slug == cover filename, keeps image refs valid
        now = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=ne.TZ)
        img = ne.make_cover(now, slug, fm)
        print(f"[ok] {img}")


if __name__ == "__main__":
    main()
