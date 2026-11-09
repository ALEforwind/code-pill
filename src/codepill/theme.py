"""界面主题：把调色板渲染成 GTK3 CSS。"""

from __future__ import annotations

import string

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

UI_FONT = '"Noto Sans CJK SC", "Source Han Sans SC", "Ubuntu", "Cantarell", "DejaVu Sans", sans-serif'
MONO_FONT = '"JetBrains Mono", "Fira Code", "Ubuntu Mono", "DejaVu Sans Mono", "Noto Sans Mono", monospace'

DARK = {
    "bg": "rgba(21, 23, 31, 0.970)",
    "border": "rgba(255, 255, 255, 0.085)",
    "fg": "#e8ebf3",
    "fg_dim": "#99a2b8",
    "fg_mute": "#707a93",
    "accent": "#7c9bff",
    "accent_soft": "rgba(124, 155, 255, 0.16)",
    "accent_border": "rgba(124, 155, 255, 0.55)",
    "hover": "rgba(255, 255, 255, 0.060)",
    "hover_strong": "rgba(255, 255, 255, 0.100)",
    "active": "rgba(124, 155, 255, 0.200)",
    "field_bg": "rgba(255, 255, 255, 0.055)",
    "chip_bg": "rgba(255, 255, 255, 0.075)",
    "scroll": "rgba(255, 255, 255, 0.180)",
    "scroll_hover": "rgba(255, 255, 255, 0.320)",
    "toast_bg": "rgba(58, 64, 86, 0.970)",
    "toast_fg": "#ffffff",
    "menu_bg": "rgba(30, 33, 44, 0.985)",
    "selection": "rgba(124, 155, 255, 0.300)",
    "danger": "#ff7b84",
    "shadow": "0 18px 48px rgba(0, 0, 0, 0.55), 0 3px 10px rgba(0, 0, 0, 0.35)",
    "shadow_pill": "0 8px 22px rgba(0, 0, 0, 0.45)",
}

LIGHT = {
    "bg": "rgba(252, 252, 255, 0.980)",
    "border": "rgba(18, 24, 40, 0.100)",
    "fg": "#1b2130",
    "fg_dim": "#667085",
    "fg_mute": "#8a93a6",
    "accent": "#3859f5",
    "accent_soft": "rgba(56, 89, 245, 0.100)",
    "accent_border": "rgba(56, 89, 245, 0.450)",
    "hover": "rgba(18, 24, 40, 0.050)",
    "hover_strong": "rgba(18, 24, 40, 0.080)",
    "active": "rgba(56, 89, 245, 0.130)",
    "field_bg": "rgba(18, 24, 40, 0.040)",
    "chip_bg": "rgba(18, 24, 40, 0.060)",
    "scroll": "rgba(18, 24, 40, 0.180)",
    "scroll_hover": "rgba(18, 24, 40, 0.320)",
    "toast_bg": "rgba(27, 33, 48, 0.950)",
    "toast_fg": "#ffffff",
    "menu_bg": "#ffffff",
    "selection": "rgba(56, 89, 245, 0.180)",
    "danger": "#d92d3f",
    "shadow": "0 18px 48px rgba(20, 28, 50, 0.20), 0 3px 10px rgba(20, 28, 50, 0.10)",
    "shadow_pill": "0 8px 22px rgba(20, 28, 50, 0.18)",
}

PALETTES = {"dark": DARK, "light": LIGHT}

_CSS = string.Template(
    """
/* ---------- 基础 ---------- */
#codepill-root { background-color: transparent; }

window#codepill-window,
window#codepill-window.background {
  background-color: transparent;
}

#card {
  background-color: $bg;
  border: 1px solid $border;
  border-radius: 18px;
  color: $fg;
  font-family: $ui_font;
}

#card.pill { border-radius: 999px; }

label { color: $fg; }
label.dim { color: $fg_dim; }
label.mute { color: $fg_mute; }

/* ---------- 顶部 ---------- */
.brand { padding: 0; }
.brand-title {
  font-size: 13.5px;
  font-weight: 700;
  color: $fg;
}
.brand-sub {
  font-size: 10.5px;
  color: $fg_mute;
}
.count {
  font-size: 10.5px;
  font-weight: 600;
  color: $fg_dim;
  background-color: $chip_bg;
  border-radius: 7px;
  padding: 1px 6px;
}

/* ---------- 图标按钮 ---------- */
button.flaticon {
  background: none;
  background-image: none;
  border: none;
  box-shadow: none;
  padding: 6px;
  min-width: 16px;
  min-height: 16px;
  border-radius: 9px;
  color: $fg_dim;
  -gtk-icon-shadow: none;
  transition: background-color 120ms ease, color 120ms ease;
}
button.flaticon:hover { background-color: $hover; color: $fg; }
button.flaticon:active { background-color: $active; color: $accent; }
button.flaticon:disabled { color: $fg_mute; }

button.small { padding: 4px 6px; border-radius: 8px; }

/* ---------- 普通按钮 ---------- */
button.ghost {
  background: none;
  background-image: none;
  border: 1px solid $border;
  box-shadow: none;
  color: $fg_dim;
  border-radius: 9px;
  padding: 6px 12px;
  font-size: 12px;
  transition: background-color 120ms ease, color 120ms ease;
}
button.ghost:hover { background-color: $hover; color: $fg; }
button.ghost:active { background-color: $active; }

button.primary {
  background-image: none;
  background-color: $accent;
  border: none;
  border-radius: 9px;
  padding: 7px 16px;
  font-weight: 600;
  font-size: 12px;
  color: #ffffff;
  box-shadow: none;
  transition: background-color 120ms ease;
}
button.primary:hover { background-color: $accent; }
button.primary:active { background-color: $accent; }

button.danger-text { color: $danger; }
button.danger-text:hover { background-color: $hover; color: $danger; }

/* ---------- 搜索 / 输入 ---------- */
entry.search {
  background-color: $field_bg;
  background-image: none;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 6px 8px;
  color: $fg;
  caret-color: $accent;
  font-size: 12.5px;
  transition: border-color 120ms ease, background-color 120ms ease;
}
entry.search:focus { border-color: $accent_border; background-color: $field_bg; }
entry.search image { color: $fg_mute; }
entry.search selection { background-color: $selection; color: $fg; }

entry.field {
  background-color: $field_bg;
  background-image: none;
  border: 1px solid $border;
  border-radius: 10px;
  padding: 7px 10px;
  color: $fg;
  caret-color: $accent;
  font-size: 12.5px;
}
entry.field:focus { border-color: $accent_border; }
entry.field selection { background-color: $selection; color: $fg; }

textview.editor {
  background-color: $field_bg;
  border: 1px solid $border;
  border-radius: 10px;
  padding: 4px;
}
textview.editor text {
  background-color: transparent;
  color: $fg;
  font-family: $mono_font;
  font-size: 12px;
}
textview.editor:focus { border-color: $accent_border; }
textview.editor selection { background-color: $selection; }
textview.editor border { border-radius: 10px; }

/* ---------- 滚动 ---------- */
scrolledwindow { background-color: transparent; }
scrolledwindow > viewport { background-color: transparent; }
scrolledwindow undershoot.top,
scrolledwindow undershoot.bottom,
scrolledwindow overshoot.top,
scrolledwindow overshoot.bottom { background: none; }

scrollbar { background-color: transparent; border: none; }
scrollbar trough { background-color: transparent; border: none; }
scrollbar slider {
  background-color: $scroll;
  border-radius: 999px;
  min-width: 5px;
  min-height: 28px;
  border: none;
}
scrollbar slider:hover { background-color: $scroll_hover; }
scrollbar.overlay-indicator slider { min-width: 4px; min-height: 24px; }

/* ---------- 片段列表 ---------- */
list { background-color: transparent; }
row.snip-row {
  background-color: transparent;
  border: none;
  padding: 0;
  margin: 0 0 2px 0;
}
row.snip-row:hover { background-color: transparent; }
row.snip-row:selected { background-color: transparent; }

.snip {
  border-radius: 12px;
  transition: background-color 100ms ease;
}
.snip:hover { background-color: $hover; }
.snip.copied { background-color: $accent_soft; }

.snip-title {
  font-size: 12.8px;
  font-weight: 600;
  color: $fg;
}
.snip-preview {
  font-family: $mono_font;
  font-size: 11px;
  color: $fg_dim;
}
.snip-meta {
  font-size: 10px;
  color: $fg_mute;
}
.tag {
  font-size: 10px;
  color: $fg_dim;
  background-color: $chip_bg;
  border-radius: 5px;
  padding: 1px 5px;
}
.pin-dot { color: $accent; font-size: 10px; }

button.flaticon.copy { color: $fg_mute; }
.snip:hover button.flaticon.copy { color: $fg; }
.snip.kbd { background-color: $hover; }
button.toast-action {
  background: none;
  background-image: none;
  border: none;
  box-shadow: none;
  padding: 6px 10px;
  color: $accent;
  font-weight: 600;
  font-size: 12px;
}

/* ---------- 标签过滤器 ---------- */
button.chip {
  background-color: $chip_bg;
  background-image: none;
  border: none;
  box-shadow: none;
  border-radius: 999px;
  padding: 4px 10px;
  min-height: 0;
  font-size: 11.5px;
  color: $fg_dim;
  transition: background-color 120ms ease, color 120ms ease;
}
button.chip:hover { background-color: $hover_strong; color: $fg; }
button.chip.active { background-color: $accent_soft; color: $accent; font-weight: 600; }

/* ---------- 分区 / 空状态 ---------- */
.section {
  font-size: 10.5px;
  font-weight: 700;
  color: $fg_mute;
}
.empty-title { font-size: 13px; color: $fg_dim; }
.empty-sub { font-size: 11.5px; color: $fg_mute; }

/* ---------- 设置行 ---------- */
.set-title { font-size: 12.8px; color: $fg; }
.set-sub { font-size: 10.8px; color: $fg_mute; }
.setting:hover { background-color: $hover; border-radius: 10px; }

switch {
  background-color: $chip_bg;
  background-image: none;
  border: 1px solid $border;
  border-radius: 999px;
  box-shadow: none;
  min-width: 38px;
  min-height: 22px;
  transition: background-color 120ms ease;
}
switch:checked { background-color: $accent; border-color: $accent; }
switch slider {
  background-color: #ffffff;
  background-image: none;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  min-width: 18px;
  min-height: 18px;
}
switch:checked slider { background-color: #ffffff; }

/* ---------- 菜单 / 提示 ---------- */
menu {
  background-color: $menu_bg;
  border: 1px solid $border;
  border-radius: 10px;
  padding: 5px;
}
menu menuitem {
  padding: 6px 12px;
  border-radius: 7px;
  font-size: 12px;
  color: $fg;
}
menu menuitem:hover { background-color: $hover; }
menu separator { background-color: $border; min-height: 1px; margin: 4px 6px; }

tooltip {
  background-color: $toast_bg;
  color: $toast_fg;
  border-radius: 8px;
  border: none;
  font-size: 11px;
  padding: 4px 8px;
}

.toast {
  background-color: $toast_bg;
  color: $toast_fg;
  border-radius: 9px;
  font-size: 12px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.30);
}
"""
)

_provider = None


def prefer_grayscale_text() -> None:
    """半透明窗口上使用灰度抗锯齿，避免彩色次像素描边造成的「彩边」。"""
    try:
        settings = Gtk.Settings.get_default()
        if settings is not None and settings.get_property("gtk-xft-rgba") != "none":
            settings.set_property("gtk-xft-rgba", "none")
    except Exception:
        pass


def css_for(theme: str) -> str:
    palette = PALETTES.get(theme, DARK)
    palette = dict(palette, ui_font=UI_FONT, mono_font=MONO_FONT)
    return _CSS.substitute(palette)


def apply(theme: str, screen: Gdk.Screen | None = None) -> None:
    """把主题 CSS 注册到屏幕上（重复调用会替换上一份）。"""
    global _provider
    prefer_grayscale_text()
    screen = screen or Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(css_for(theme).encode("utf-8"))
    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, _provider)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _provider = provider
