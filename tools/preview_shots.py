#!/usr/bin/env python3
"""生成文档用的界面截图（离屏渲染 + 合成桌面壁纸）。

用法：python3 tools/preview_shots.py [--outdir docs]
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from codepill import app as app_mod, store as store_mod, theme, ui  # noqa: E402

WALL_W, WALL_H = 1440, 900


def pump(limit: int = 300):
    for _ in range(limit):
        if not Gtk.main_iteration_do(False):
            break


def wallpaper() -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, WALL_W, WALL_H)
    cr = cairo.Context(surface)

    grad = cairo.LinearGradient(0, 0, WALL_W, WALL_H)
    grad.add_color_stop_rgb(0.0, 0.10, 0.12, 0.18)
    grad.add_color_stop_rgb(0.45, 0.13, 0.16, 0.24)
    grad.add_color_stop_rgb(1.0, 0.07, 0.08, 0.12)
    cr.set_source(grad)
    cr.paint()

    # 柔和的色块，模拟桌面壁纸的光晕
    blobs = [
        (0.18, 0.20, 420, (0.31, 0.42, 0.95, 0.30)),
        (0.82, 0.16, 360, (0.55, 0.35, 0.95, 0.22)),
        (0.72, 0.86, 480, (0.20, 0.65, 0.75, 0.16)),
    ]
    for cx, cy, r, (cr_, cg, cb, alpha) in blobs:
        rad = cairo.RadialGradient(cx * WALL_W, cy * WALL_H, 0, cx * WALL_W, cy * WALL_H, r)
        rad.add_color_stop_rgba(0, cr_, cg, cb, alpha)
        rad.add_color_stop_rgba(1, cr_, cg, cb, 0)
        cr.set_source(rad)
        cr.paint()

    # 一点点噪点，避免色带
    import random

    random.seed(7)
    cr.set_source_rgba(1, 1, 1, 1)
    for _ in range(2600):
        x = random.random() * WALL_W
        y = random.random() * WALL_H
        cr.set_source_rgba(1, 1, 1, random.random() * 0.035)
        cr.rectangle(x, y, 1.4, 1.4)
        cr.fill()

    # 顶部一条若隐若现的顶栏
    cr.set_source_rgba(0, 0, 0, 0.22)
    cr.rectangle(0, 0, WALL_W, 34)
    cr.fill()
    cr.set_source_rgba(1, 1, 1, 0.10)
    cr.rectangle(0, 33, WALL_W, 1)
    cr.fill()
    return surface


def rounded_rect(cr, x, y, w, h, r=12):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def widget_png(store: store_mod.Store, mode: str, theme_name: str, prepare=None) -> cairo.ImageSurface:
    theme.apply(theme_name)
    ui_ = ui.UI(store)
    if prepare:
        prepare(ui_)
    else:
        ui_._render(mode)
    pump()
    offscreen = Gtk.OffscreenWindow()
    offscreen.add(ui_)
    offscreen.show_all()
    pump()
    pixbuf = offscreen.get_pixbuf()
    pixbuf.savev("/tmp/_shot_raw.png", "png", [], [])
    surface = cairo.ImageSurface.create_from_png("/tmp/_shot_raw.png")

    w, h = surface.get_width(), surface.get_height()
    scaled = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(scaled)
    cr.scale(w / surface.get_width(), h / surface.get_height())
    cr.set_source_surface(surface, 0, 0)
    pattern = cr.get_source()
    pattern.set_filter(cairo.FILTER_GOOD)
    cr.paint()
    offscreen.destroy()
    return scaled


def compose(widget: cairo.ImageSurface, out: Path, x: int, y: int):
    base = wallpaper()
    cr = cairo.Context(base)
    cr.set_source_surface(widget, x, y)
    cr.paint()
    base.write_to_png(str(out))
    print(f"  {out} ({base.get_width()}x{base.get_height()})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default="docs")
    args = parser.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not Gtk.init_check([])[0]:
        print("需要图形界面（DISPLAY）", file=sys.stderr)
        return 1
    app_mod._register_icons()
    tmp = Path("/tmp/codepill-shots")
    tmp.mkdir(exist_ok=True)

    store = store_mod.Store(tmp / "snippets.json")
    list_shot = widget_png(store, "list", "dark")
    compose(list_shot, outdir / "screenshot-list.png", WALL_W - list_shot.get_width() - 48, 60)

    pill_store = store_mod.Store(tmp / "snippets.json")
    pill_shot = widget_png(pill_store, "pill", "dark")
    compose(pill_shot, outdir / "screenshot-pill.png", WALL_W - pill_shot.get_width() - 48, 60)

    editor_store = store_mod.Store(tmp / "snippets.json")
    sample = next(s for s in editor_store.snippets() if "Git" in s["title"])

    def prep(ui_):
        ui_.edit_snippet(sample)

    editor_shot = widget_png(editor_store, "editor", "dark", prepare=prep)
    compose(editor_shot, outdir / "screenshot-editor.png",
            (WALL_W - editor_shot.get_width()) // 2, 110)

    light_store = store_mod.Store(tmp / "snippets.json")
    light_shot = widget_png(light_store, "list", "light")
    compose(light_shot, outdir / "screenshot-light.png",
            (WALL_W - light_shot.get_width()) // 2, 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
