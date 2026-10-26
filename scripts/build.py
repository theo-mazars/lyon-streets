#!/usr/bin/env python3
"""Build the standalone page: src/template.html + data/lyon-data.json -> dist/index.html.

Usage:
    python3 scripts/build.py                  # writes dist/index.html
    python3 scripts/build.py --out site/index.html

Standard library only.
"""
import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--template", type=pathlib.Path, default=ROOT / "src" / "template.html")
    ap.add_argument("--data", type=pathlib.Path, default=ROOT / "data" / "lyon-data.json")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "dist" / "index.html")
    args = ap.parse_args()

    template = args.template.read_text(encoding="utf-8")
    if template.count("__DATA__") != 1:
        raise SystemExit(f"{args.template}: expected exactly one __DATA__ placeholder")

    data = args.data.read_text(encoding="utf-8")
    json.loads(data)  # fail early on a broken data file
    # The data sits inside a <script> tag, so "</" must not appear literally.
    html = template.replace("__DATA__", data.replace("</", "<\\/"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(html.encode()) // 1024} KB)")


if __name__ == "__main__":
    main()
