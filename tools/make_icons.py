#!/usr/bin/env python3
"""把 SVG 图标渲染成各尺寸 PNG，输出到 <out>/<size>x<size>/apps/codepill.png。"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--svg", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    svg = Path(args.svg)
    out = Path(args.out)
    if not svg.exists():
        print(f"找不到 SVG：{svg}", file=sys.stderr)
        return 1

    for size in SIZES:
        target = out / f"{size}x{size}" / "apps"
        target.mkdir(parents=True, exist_ok=True)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(svg), size, size, True)
        pixbuf.savev(str(target / "codepill.png"), "png", [], [])
        print(f"  {size}x{size}: {target / 'codepill.png'}")

    scalable = out / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    shutil.copy2(svg, scalable / "codepill.svg")
    print(f"  scalable: {scalable / 'codepill.svg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
