"""程序入口：单实例应用、命令行参数、主题初始化。"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, store as store_mod, theme, ui  # noqa: E402

APP_ID = "io.github.codepill"

ASSETS = Path(__file__).resolve().parent / "assets"
ICON_FILE = ASSETS / "hicolor" / "scalable" / "apps" / "codepill.svg"


def _register_icons() -> None:
    if ASSETS.is_dir():
        try:
            Gtk.IconTheme.get_default().append_search_path(str(ASSETS))
        except Exception:
            pass
    if ICON_FILE.exists():
        try:
            Gtk.Window.set_default_icon_from_file(str(ICON_FILE))
        except Exception:
            pass


class App(Gtk.Application):
    def __init__(self, store: store_mod.Store):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.store = store
        self.window: ui.PillWindow | None = None

    def do_startup(self):  # noqa: N802
        Gtk.Application.do_startup(self)
        _register_icons()
        theme.apply(self.store.get_setting("theme"))
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_signal)

    def _on_signal(self):
        self.store.save()
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_activate(self):  # noqa: N802
        if self.window is None:
            self.window = ui.PillWindow(self.store)
            self.window.ui.connect("quit", lambda *_: self.quit())
            # 交给 Gtk.Application 托管，否则 activate 结束后进程会立刻退出
            self.add_window(self.window)
            self.window.show_all()
        else:
            # 再次从菜单启动时，直接把面板展开
            self.window.present()
            if self.window.ui.mode == "pill":
                self.window.ui.show_list()


def _pump(rounds: int = 40, delay: float = 0.01):
    """跑一会儿主循环：既处理 idle 回调，也给 X11 的 ConfigureNotify 留出时间。"""
    for _ in range(rounds):
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(delay)


def _selftest(store, shot_path: str | None = None) -> int:
    """在真实窗口里跑一遍关键流程（开发自检用）。"""
    if not Gtk.init_check([])[0]:
        print("NO DISPLAY", file=sys.stderr)
        return 1
    _register_icons()
    theme.apply(store.get_setting("theme"))
    # 自检时关掉「复制后自动收起」，否则计时器会打乱后续尺寸检查
    old_auto_close = store.get_setting("auto_collapse")
    store.set_setting("auto_collapse", False)
    win = ui.PillWindow(store)
    win.show_all()
    _pump()
    problems = []

    def check(label, condition):
        print(("PASS " if condition else "FAIL ") + label)
        if not condition:
            problems.append(label)

    gdk_window = win.get_window()
    check("窗口已显示", gdk_window is not None and gdk_window.is_viewable())
    check("无边框 + 置顶", not win.get_decorated() and win.keep_above)
    check("初始为悬浮球", win.ui.mode == "pill")

    win.ui.show_list()
    _pump()
    check("展开为列表", win.ui.mode == "list")
    check("列表有内容", len(win.ui._rows) > 0)

    if win.ui._rows:
        snippet = win.ui._rows[0][1]
        win.ui._copy(snippet)
        _pump(10)
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        check("复制到剪贴板", text == snippet["content"])
        check("记录使用次数", store.get(snippet["id"])["uses"] >= 1)

    win.ui.show_settings()
    _pump()
    check("打开设置页", win.ui.mode == "settings")
    win.ui.show_list()
    _pump()

    x, y = win.get_position()
    w, h = win.get_size()
    print(f"    窗口位置 {x},{y} 尺寸 {w}x{h} 锚点 {win._anchor}")
    check("窗口在屏幕范围内", x >= 0 and y >= 0 and x + w <= 10000)

    if shot_path:
        _pump(10)
        pb = Gdk.pixbuf_get_from_window(gdk_window, 0, 0, w, h)
        if pb:
            pb.savev(shot_path, "png", [], [])
            print("    截图已保存", shot_path)

    win.ui.collapse()
    _pump()
    check("收起回悬浮球", win.ui.mode == "pill")
    store.set_setting("auto_collapse", old_auto_close)
    store.save()
    win.destroy()
    return 0 if not problems else 2


def _render_mode(args) -> int:
    if not Gtk.init_check([])[0]:
        print("无法连接到图形界面（DISPLAY 未设置）", file=sys.stderr)
        return 1
    _register_icons()
    store = store_mod.Store(args.data) if args.data else store_mod.Store()
    theme.apply(args.theme or store.get_setting("theme"))
    pixbuf = ui.render_preview(store, args.mode, args.scale)
    out = Path(args.render).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(out), "png", [], [])
    print(f"已生成预览图：{out} ({pixbuf.get_width()}x{pixbuf.get_height()})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codepill",
        description="代码贴 CodePill —— 悬浮在桌面的代码 / 命令行速取工具",
    )
    parser.add_argument("--version", action="version", version=f"代码贴 CodePill {__version__}")
    parser.add_argument("--data", metavar="FILE", help="使用指定的数据文件（默认 ~/.config/codepill/snippets.json）")
    parser.add_argument("--render", metavar="PNG", help="离屏渲染界面截图后退出（开发用）")
    parser.add_argument(
        "--mode",
        default="list",
        choices=["pill", "list", "editor", "settings"],
        help="配合 --render 使用，指定要渲染的界面",
    )
    parser.add_argument("--theme", choices=["dark", "light"], help="配合 --render 使用")
    parser.add_argument("--scale", type=float, default=1.0, help="配合 --render 使用的缩放比例")
    parser.add_argument("--debug", action="store_true", help="输出调试信息")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--shot", metavar="PNG", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.render:
        return _render_mode(args)

    _register_icons()
    store = store_mod.Store(args.data)
    if args.selftest:
        return _selftest(store, args.shot)

    app = App(store)
    try:
        return app.run([])
    except Exception as exc:  # 兜底：DBus 不可用时退化为普通窗口
        if args.debug:
            raise
        print(f"[codepill] 应用启动失败：{exc}", file=sys.stderr)
        return 1
