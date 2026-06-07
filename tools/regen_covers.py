#!/usr/bin/env python3
"""regen_covers.py - rebuild cover images for all existing posts.

Run after changing make_cover() in new_entry.py so older entries pick up the new
cover design. Uses each post's own front matter (mood, tape, spark) and its date,
rewrites the post's image: field to the new file, and removes any stale .svg cover.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import new_entry as ne  # noqa: E402

JOURNAL = ne.ROOT / "assets" / "journal"


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
        text = f.read_text(encoding="utf-8")
        fm, _ = ne.split_front_matter(text)
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(.+)\.md$", f.name)
        if not fm or not m:
            print(f"[skip] {f.name}")
            continue
        slug = m.group(4)
        now = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=ne.TZ)
        img = ne.make_cover(now, slug, fm)            # writes the new PNG

        # Point the post at the new image and drop a stale .svg cover if present.
        new_text, n = re.subn(r'(?m)^image:\s*".*?"\s*$', f'image: "{img}"', text, count=1)
        if n == 0:
            new_text = f'image: "{img}"\n' + text  # add if it was missing
        if new_text != text:
            f.write_text(new_text, encoding="utf-8")
        old_svg = JOURNAL / f"{now.strftime('%Y-%m-%d')}-{slug}.svg"
        if old_svg.exists():
            old_svg.unlink()
        print(f"[ok] {img}")


if __name__ == "__main__":
    main()
