"""悬浮卡片界面。

结构：UI（Gtk.Box，卡片本体）放在 PillWindow（无边框、置顶、透明）里。
卡片有四种形态：pill（收起的小胶囊）、list（片段列表）、editor（编辑器）、
settings（设置）。UI 通过信号和窗口通信，因此同一个卡片也能放进离屏窗口里
渲染预览图。
"""

from __future__ import annotations

import math
import time

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from . import __version__, store as store_mod, theme  # noqa: E402

# 卡片四周留出的透明区域，用来画阴影
PAD = 18

CARD_SIZES = {
    "pill": (178, 48),
    "list": (412, 588),
    "editor": (412, 548),
    "settings": (412, 452),
}

ROW_HEIGHT = 55


def _ellipsize(label: Gtk.Label, chars: int = 30) -> Gtk.Label:
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(chars)
    label.set_xalign(0.0)
    return label


def _rounded_rect(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _hexpand(widget: Gtk.Widget, value: bool = True) -> Gtk.Widget:
    widget.set_hexpand(value)
    return widget


class UI(Gtk.Box):
    """卡片本体。"""

    __gsignals__ = {
        "request-size": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "collapse": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "quit": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "move-begin": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "move-update": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "move-end": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, store: store_mod.Store, clipboard_writer=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_name("codepill-root")

        self.store = store
        self._write_clipboard = clipboard_writer or self._default_clipboard
        self.mode = "pill"
        self.search_text = ""
        self.active_tag: str | None = None
        self.editing: dict | None = None
        self._kbd_index = 0
        self._rows: list[tuple[Gtk.Widget, dict]] = []
        self._toast_timer = 0
        self._toast_action = None
        self._resize_id = 0
        self._press_origin = None
        self._drag_started = False
        self._drag_cursor = None

        # 内部的卡片容器
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.card.set_name("card")
        self.card.set_margin_start(PAD)
        self.card.set_margin_end(PAD)
        self.card.set_margin_top(PAD)
        self.card.set_margin_bottom(PAD)
        self.add(self.card)

        self.connect("draw", self._on_draw)
        self.connect("key-press-event", self._on_key_press)
        self.show_all()
        self._render("pill")

    # ------------------------------------------------------------------
    # 基础绘制 / 尺寸
    # ------------------------------------------------------------------

    def _on_draw(self, _widget, cr):
        # 先把整块区域清成透明，阴影和圆角才不会被底色填满
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.restore()
        self._draw_shadow(cr)
        return False

    def _draw_shadow(self, cr):
        """在卡片四周画一圈柔和阴影，并且在到达窗口边缘前淡出为 0，
        这样就不会出现被窗口裁断的「方框黑边」。"""
        size = getattr(self, "_card_size", None)
        if not size or size[1] <= 0:
            return
        width, height = size
        radius = height / 2.0 if self.mode == "pill" else 18.0
        max_alpha = 0.20 if self.store.get_setting("theme") == "light" else 0.45
        steps = 18
        previous = 0.0
        for i in range(steps, 0, -1):
            t = i / steps                      # 1.0 = 最外圈
            spread = t * PAD * 0.92            # 留一点余量，确保边缘 alpha 为 0
            target = max_alpha * (1.0 - t) ** 2
            alpha = (target - previous) / (1.0 - previous) if previous < 0.999 else 0.0
            previous = target
            if alpha <= 0.0:
                continue
            _rounded_rect(cr, PAD - spread, PAD - spread,
                          width + spread * 2, height + spread * 2, radius + spread)
            cr.set_source_rgba(0, 0, 0, alpha)
            cr.fill()

    def _request(self, width: int, height: int | None = None):
        """height 为 None 时按内容自然高度布局（列表会随条目多少变高变矮）。"""
        # 先清掉之前写死的尺寸请求，否则测量到的还是旧值
        self.set_size_request(-1, -1)
        self.card.set_size_request(width, -1)
        if height is None:
            self.queue_resize()
            height = max(90, self.get_preferred_height()[1] - PAD * 2)
        self.card.set_size_request(width, height)
        self._card_size = (width, height)
        self.set_size_request(width + PAD * 2, height + PAD * 2)
        self.emit("request-size", width, height)

    def _provisional_list_height(self) -> int:
        rows = len(self.store.query(self.search_text, self.active_tag))
        chrome = 161 + (32 if self.store.tags() else 0)
        return max(230, min(CARD_SIZES["list"][1], chrome + rows * ROW_HEIGHT))

    def _schedule_resize(self):
        """空闲时按内容重新计算高度（此时 GTK 已经完成布局，测量才准确）。"""
        if self._resize_id:
            return
        self._resize_id = GLib.idle_add(self._apply_natural_size)

    def _apply_natural_size(self):
        self._resize_id = 0
        width = {
            "pill": CARD_SIZES["pill"][0],
            "list": CARD_SIZES["list"][0],
            "editor": CARD_SIZES["editor"][0],
            "settings": CARD_SIZES["settings"][0],
        }.get(self.mode, CARD_SIZES["list"][0])
        self._request(width)
        return False

    def _clear_card(self):
        for child in list(self.card.get_children()):
            self.card.remove(child)

    def _render(self, mode: str):
        self.mode = mode
        self._clear_card()
        self.card.get_style_context().remove_class("pill")
        if mode == "pill":
            self.card.get_style_context().add_class("pill")
            self._build_pill()
        elif mode == "editor":
            self._build_editor()
        elif mode == "settings":
            self._build_settings()
        else:
            self._build_list()
        self.card.show_all()
        if mode == "pill":
            self._request(*CARD_SIZES["pill"])
        else:
            self._hide_toast_now()
            # 先给一个接近的尺寸，避免展开时闪一下小窗口；随后按内容自然高度微调
            width, height = CARD_SIZES.get(mode, CARD_SIZES["list"])
            if mode == "list":
                height = self._provisional_list_height()
            self._request(width, height)
            self._schedule_resize()

    # ------------------------------------------------------------------
    # 小组件工厂
    # ------------------------------------------------------------------

    def _icon(self, name: str, size: int = 16, fallback: str = ""):
        theme_ = Gtk.IconTheme.get_default()
        if name and theme_.has_icon(name):
            img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.MENU)
            img.set_pixel_size(size)
            return img
        lbl = Gtk.Label(label=fallback or "•")
        lbl.get_style_context().add_class("dim")
        return lbl

    def _app_icon(self, size: int = 22):
        theme_ = Gtk.IconTheme.get_default()
        if theme_.has_icon("codepill"):
            img = Gtk.Image.new_from_icon_name("codepill", Gtk.IconSize.DIALOG)
            img.set_pixel_size(size)
            return img
        return self._icon("edit-copy-symbolic", size)

    def _icon_button(self, name, tooltip, callback, fallback="•", size=16, css="flaticon"):
        btn = Gtk.Button()
        btn.get_style_context().add_class(css)
        btn.add(self._icon(name, size, fallback))
        btn.set_tooltip_text(tooltip)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_can_focus(False)
        btn.connect("clicked", lambda *_: callback())
        return btn

    def _label(self, text: str, css: str = "", size: int | None = None) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0.0)
        if css:
            lbl.get_style_context().add_class(css)
        if size:
            lbl.set_size_request(-1, size)
        return lbl

    def _drag_handle(self, eventbox: Gtk.EventBox, on_click=None):
        """让 EventBox 支持「按住拖动窗口」，以及「单击」。"""
        eventbox.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        eventbox.connect("realize", self._on_handle_realize)
        eventbox.connect("button-press-event", self._on_drag_press)
        eventbox.connect("motion-notify-event", self._on_drag_motion)
        eventbox.connect("button-release-event", lambda w, e: self._on_drag_release(w, e, on_click))
        return eventbox

    def _on_handle_realize(self, widget):
        try:
            display = widget.get_display()
            self._drag_cursor = Gdk.Cursor.new_from_name(display, "grab")
            widget.get_window().set_cursor(self._drag_cursor)
        except Exception:
            pass

    def _on_drag_press(self, widget, event):
        if event.button != 1:
            return False
        self._press_origin = (event.x_root, event.y_root)
        self._drag_started = False
        return False

    def _on_drag_motion(self, widget, event):
        if self._press_origin is None:
            return False
        dx = event.x_root - self._press_origin[0]
        dy = event.y_root - self._press_origin[1]
        if not self._drag_started and (abs(dx) > 3 or abs(dy) > 3):
            self._drag_started = True
            self.emit("move-begin")
            try:
                widget.get_window().set_cursor(Gdk.Cursor.new_from_name(widget.get_display(), "grabbing"))
            except Exception:
                pass
        if self._drag_started:
            self.emit("move-update", int(dx), int(dy))
            return True
        return False

    def _on_drag_release(self, widget, event, on_click=None):
        was_drag = self._drag_started
        self._press_origin = None
        self._drag_started = False
        try:
            widget.get_window().set_cursor(self._drag_cursor)
        except Exception:
            pass
        if was_drag:
            self.emit("move-end")
            return True
        if event.button == 1 and on_click is not None:
            on_click()
            return True
        return False

    # ------------------------------------------------------------------
    # 收起状态（悬浮胶囊）
    # ------------------------------------------------------------------

    def _build_pill(self):
        wrap = Gtk.EventBox()
        wrap.set_visible_window(True)
        wrap.get_style_context().add_class("pill-body")
        wrap.set_tooltip_text("单击展开代码贴 · 拖动可移动")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(13)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.add(self._app_icon(22))
        box.add(self._label("代码贴", "brand-title"))
        count = self._label(str(len(self.store.data["snippets"])), "count")
        count.set_valign(Gtk.Align.CENTER)
        box.add(count)
        wrap.add(box)
        self.card.add(wrap)

        self._drag_handle(wrap, on_click=lambda: self.show_list())

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    def _build_list(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_margin_top(10)
        page.set_margin_bottom(10)

        # 顶部：品牌区（可拖动）+ 操作按钮
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.set_margin_start(12)
        header.set_margin_end(8)

        brand = Gtk.EventBox()
        brand.set_visible_window(False)
        brand_ctx = brand.get_style_context()
        brand_ctx.add_class("brand")
        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        brand_box.add(self._app_icon(22))
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_row.add(self._label("代码贴", "brand-title"))
        count = self._label(f"{len(self.store.data['snippets'])} 条", "brand-sub")
        count.set_valign(Gtk.Align.CENTER)
        title_row.add(count)
        text_box.add(title_row)
        text_box.add(self._label("单击片段即可复制", "brand-sub"))
        brand_box.add(text_box)
        brand.add(brand_box)
        brand.set_hexpand(True)
        header.add(brand)
        self._drag_handle(brand)

        header.add(self._icon_button("list-add-symbolic", "新建片段 (Ctrl+N)", self.new_snippet, "＋"))
        header.add(self._icon_button("emblem-system-symbolic", "设置", self.show_settings, "⚙"))
        header.add(self._icon_button("pan-up-symbolic", "收起 (Esc)", self.collapse, "▴"))
        page.add(header)

        # 搜索框
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.get_style_context().add_class("search")
        self.search_entry.set_placeholder_text("搜索标题、内容或标签…")
        self.search_entry.set_margin_start(12)
        self.search_entry.set_margin_end(12)
        self.search_entry.connect("changed", self._on_search_changed)
        self.search_entry.connect("activate", self._copy_first_match)
        if self.search_text:
            self.search_entry.set_text(self.search_text)
        page.add(self.search_entry)

        # 标签过滤器
        self.chips_scroller = Gtk.ScrolledWindow()
        self.chips_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.chips_scroller.set_overlay_scrolling(True)
        self.chips_scroller.set_margin_start(12)
        self.chips_scroller.set_margin_end(12)
        self.chips_scroller.set_min_content_height(30)
        self.chips_scroller.set_propagate_natural_height(True)
        chips_viewport = Gtk.Viewport()
        chips_viewport.set_shadow_type(Gtk.ShadowType.NONE)
        self.chips_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.chips_box.set_valign(Gtk.Align.CENTER)
        chips_viewport.add(self.chips_box)
        self.chips_scroller.add(chips_viewport)
        page.add(self.chips_scroller)

        # 列表 + 空状态 + 提示条
        stack = Gtk.Stack()
        stack.set_vexpand(True)
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(120)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_activate_on_single_click(False)
        self.listbox.get_style_context().add_class("snip-list")
        self.list_scroller = Gtk.ScrolledWindow()
        self.list_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.list_scroller.set_overlay_scrolling(True)
        self.list_scroller.set_propagate_natural_height(True)
        self.list_scroller.set_max_content_height(440)
        self.list_scroller.set_min_content_height(60)
        self.list_scroller.add(self.listbox)
        self.list_scroller.set_vexpand(True)
        stack.add_named(self.list_scroller, "list")

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty.set_valign(Gtk.Align.CENTER)
        empty.set_halign(Gtk.Align.CENTER)
        self._empty_icon = self._icon("edit-copy-symbolic", 34)
        empty.add(self._empty_icon)
        self._empty_title = self._label("这里还空着", "empty-title")
        empty.add(self._empty_title)
        self._empty_sub = self._label("把常用的命令和代码存进来，下次一键复制", "empty-sub")
        self._empty_sub.set_line_wrap(True)
        self._empty_sub.set_max_width_chars(30)
        self._empty_sub.set_justify(Gtk.Justification.CENTER)
        self._empty_sub.set_xalign(0.5)
        empty.add(self._empty_sub)
        self._empty_btn = Gtk.Button(label="添加第一条")
        self._empty_btn.get_style_context().add_class("ghost")
        self._empty_btn.set_halign(Gtk.Align.CENTER)
        self._empty_btn.set_margin_top(6)
        self._empty_btn.connect("clicked", lambda *_: self._on_empty_action())
        empty.add(self._empty_btn)
        empty.set_size_request(-1, 250)
        stack.add_named(empty, "empty")

        self.page_stack = stack

        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.set_margin_start(8)
        holder.set_margin_end(8)
        holder.set_margin_bottom(4)
        holder.set_vexpand(True)
        holder.add(stack)
        page.add(holder)
        page.set_vexpand(True)

        self.card.add(self._wrap_toast(page))
        page.show_all()
        self._rebuild_chips()
        self._refresh_list()
        GLib.idle_add(self._focus_search, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def _focus_search(self):
        if self.mode == "list" and self.search_entry.get_visible():
            self.search_entry.grab_focus()
        return False

    def _on_search_changed(self, entry):
        self.search_text = entry.get_text()
        self._refresh_list()

    def _refresh_list(self):
        for row in self.listbox.get_children():
            self.listbox.remove(row)
        self._rows = []
        self._kbd_index = 0

        results = self.store.query(self.search_text, self.active_tag)
        for snippet in results:
            row = self._build_row(snippet)
            self.listbox.add(row)
            self._rows.append((row, snippet))

        if results:
            self.page_stack.set_visible_child_name("list")
        else:
            self._configure_empty_state(bool(self.search_text or self.active_tag))
            self.page_stack.set_visible_child_name("empty")
        self.listbox.show_all()
        # 让可视区高度正好是整数行，底部不会出现被截断的半行
        row_h = 55
        if self.listbox.get_children():
            row_h = max(30, self.listbox.get_children()[0].get_preferred_height()[1])
        self.list_scroller.set_max_content_height(max(row_h, (440 // row_h) * row_h))
        if self._rows:
            self._highlight_row(0, scroll=False, paint=False)
        self._schedule_resize()

    def _configure_empty_state(self, filtered: bool):
        if filtered:
            self._empty_title.set_text("没有匹配的片段")
            self._empty_sub.set_text("换个关键词试试，或者清除筛选条件")
            self._empty_btn.set_label("清除筛选")
        else:
            self._empty_title.set_text("这里还空着")
            self._empty_sub.set_text("把常用的命令和代码存进来，下次一键复制")
            self._empty_btn.set_label("添加第一条")

    def _on_empty_action(self):
        if self.search_text or self.active_tag:
            self.search_text = ""
            self.search_entry.set_text("")
            self.active_tag = None
            self._rebuild_chips()
            self._refresh_list()
        else:
            self.new_snippet()

    def _copy_first_match(self, _entry):
        if self._rows:
            self._highlight_row(0, scroll=False)
            self._copy(self._rows[0][1], self._rows[0][0].get_child())

    def _rebuild_chips(self):
        for child in list(self.chips_box.get_children()):
            self.chips_box.remove(child)
        tags = self.store.tags()
        self.chips_scroller.set_visible(bool(tags))
        if not tags:
            return
        for tag in tags:
            btn = Gtk.Button(label=tag)
            btn.get_style_context().add_class("chip")
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_can_focus(False)
            if tag == self.active_tag:
                btn.get_style_context().add_class("active")
            btn.connect("clicked", lambda _b, t=tag: self._set_tag(t))
            self.chips_box.add(btn)
        self.chips_box.show_all()

    def _set_tag(self, tag: str | None):
        self.active_tag = None if self.active_tag == tag else tag
        self._rebuild_chips()
        self._refresh_list()

    def _wrap_toast(self, page: Gtk.Widget) -> Gtk.Overlay:
        """给页面包一层 Overlay，底部居中的提示条就浮在内容上方。"""
        overlay = Gtk.Overlay()
        overlay.set_vexpand(True)
        overlay.add(page)

        toast_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toast_box.get_style_context().add_class("toast")

        self._toast_label = Gtk.Label(label="")
        self._toast_label.set_margin_start(14)
        self._toast_label.set_margin_end(2)
        self._toast_label.set_margin_top(7)
        self._toast_label.set_margin_bottom(7)
        toast_box.add(self._toast_label)

        self._toast_button = Gtk.Button()
        self._toast_button.get_style_context().add_class("toast-action")
        self._toast_button.set_relief(Gtk.ReliefStyle.NONE)
        self._toast_button.set_no_show_all(True)
        self._toast_button.set_margin_end(10)
        toast_box.add(self._toast_button)

        self._toast_revealer = Gtk.Revealer()
        self._toast_revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self._toast_revealer.set_transition_duration(140)
        self._toast_revealer.set_halign(Gtk.Align.CENTER)
        self._toast_revealer.set_valign(Gtk.Align.END)
        self._toast_revealer.set_margin_bottom(16)
        self._toast_revealer.add(toast_box)
        overlay.add_overlay(self._toast_revealer)
        self._toast_overlay = overlay
        # 提示条不显示时完全不拦截鼠标事件，避免挡住下面的控件
        try:
            overlay.set_overlay_pass_through(self._toast_revealer, True)
        except AttributeError:
            pass
        return overlay

    # ------------------------------------------------------------------
    # 单行
    # ------------------------------------------------------------------

    def _build_row(self, snippet: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("snip-row")

        eb = Gtk.EventBox()
        eb.set_visible_window(True)
        eb.get_style_context().add_class("snip")
        eb.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        eb.connect("button-press-event", self._on_row_press, snippet)
        eb.set_tooltip_text("单击复制 · 右键更多操作")

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.set_margin_start(10)
        outer.set_margin_end(10)
        outer.set_margin_top(9)
        outer.set_margin_bottom(9)

        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.set_hexpand(True)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        if snippet["pinned"]:
            pin = self._icon("view-pin-symbolic", 11)
            pin.set_tooltip_text("已置顶")
            title_row.add(pin)
        title = self._label(snippet["title"], "snip-title")
        _ellipsize(title, 26)
        title_row.add(title)
        if snippet["tags"]:
            tag_text = " · ".join(snippet["tags"][:3])
            tag_label = self._label(tag_text, "snip-meta")
            tag_label.set_hexpand(True)
            tag_label.set_halign(Gtk.Align.END)
            _ellipsize(tag_label, 16)
            title_row.add(tag_label)
        texts.add(title_row)

        preview_text = "  ".join(line.strip() for line in snippet["content"].splitlines()[:2])
        preview = self._label(preview_text or " ", "snip-preview")
        _ellipsize(preview, 44)
        texts.add(preview)

        outer.add(texts)

        copy_btn = self._icon_button(
            "edit-copy-symbolic",
            "复制",
            lambda s=snippet: self._copy(s),
            "⧉",
            14,
            "flaticon small copy",
        )
        copy_btn.set_valign(Gtk.Align.CENTER)
        outer.add(copy_btn)

        eb.add(outer)
        row.add(eb)
        return row

    def _on_row_press(self, widget, event, snippet):
        if event.button == 1:
            self._kbd_index = next(
                (i for i, (_w, s) in enumerate(self._rows) if s["id"] == snippet["id"]), 0
            )
            self._copy(snippet, widget)
            return True
        if event.button == 3:
            self._show_row_menu(snippet, event)
            return True
        return False

    def _show_row_menu(self, snippet, event):
        menu = Gtk.Menu()

        def add(label, callback):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda *_: callback())
            menu.append(item)

        add("复制", lambda: self._copy(snippet))
        add("编辑", lambda: self.edit_snippet(snippet))
        add("取消置顶" if snippet["pinned"] else "置顶", lambda: self._toggle_pin(snippet))
        menu.append(Gtk.SeparatorMenuItem())
        add("删除", lambda: self._delete(snippet))
        menu.show_all()
        menu.popup_at_pointer(event)

    def _copy(self, snippet: dict, widget=None):
        if not self._write_clipboard(snippet["content"]):
            self.toast("复制失败：无法访问剪贴板")
            return
        self.store.record_use(snippet["id"])
        if widget is not None:
            ctx = widget.get_style_context()
            ctx.add_class("copied")
            GLib.timeout_add(520, self._unflash, widget)
        self.toast("已复制「%s」" % (snippet["title"][:18]))
        if self.store.get_setting("auto_collapse"):
            GLib.timeout_add(560, self._auto_collapse)

    def _unflash(self, widget):
        if widget.get_parent() is not None:
            widget.get_style_context().remove_class("copied")
        return False

    def _auto_collapse(self):
        if self.mode == "list" and self.store.get_setting("auto_collapse"):
            self.collapse()
        return False

    def _toggle_pin(self, snippet):
        pinned = self.store.toggle_pin(snippet["id"])
        self._refresh_list()
        self.toast("已置顶" if pinned else "已取消置顶")

    def _delete(self, snippet):
        self.store.delete(snippet["id"])
        self._rebuild_chips()
        self._refresh_list()
        self.toast(
            "已删除「%s」" % snippet["title"][:14],
            action_label="撤销",
            action_cb=lambda: self._undo_delete(snippet),
            timeout=5000,
        )

    def _undo_delete(self, snippet):
        self.store.restore(snippet)
        self._rebuild_chips()
        self._refresh_list()
        self.toast("已恢复")

    # ------------------------------------------------------------------
    # 键盘
    # ------------------------------------------------------------------

    def _highlight_row(self, index: int, scroll: bool = True, paint: bool = True):
        for i, (row, _s) in enumerate(self._rows):
            ctx = row.get_child().get_style_context() if row.get_child() else None
            if ctx is None:
                continue
            if i == index and paint:
                ctx.add_class("kbd")
            else:
                ctx.remove_class("kbd")
        self._kbd_index = index
        if scroll and self._rows:
            row = self._rows[index][0]
            alloc = row.get_allocation()
            adj = self.list_scroller.get_vadjustment()
            top = alloc.y
            bottom = alloc.y + alloc.height
            if top < adj.get_value():
                adj.set_value(top)
            elif bottom > adj.get_value() + adj.get_page_size():
                adj.set_value(bottom - adj.get_page_size())

    def _on_key_press(self, _widget, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        key = Gdk.keyval_name(event.keyval) or ""

        if key == "Escape":
            if self.mode == "editor":
                self.show_list()
                return True
            if self.mode == "settings":
                self.show_list()
                return True
            if self.mode == "list":
                self.collapse()
                return True
        if ctrl and key.lower() == "n":
            self.new_snippet()
            return True
        if ctrl and key.lower() == "f" and self.mode == "list":
            self.search_entry.grab_focus()
            return True
        if self.mode == "list":
            if key in ("Down", "KP_Down"):
                if self._rows:
                    self._highlight_row(min(len(self._rows) - 1, self._kbd_index + 1))
                return True
            if key in ("Up", "KP_Up"):
                if self._rows:
                    self._highlight_row(max(0, self._kbd_index - 1))
                return True
            if key in ("Return", "KP_Enter"):
                if self._rows:
                    self._copy(self._rows[self._kbd_index][1], self._rows[self._kbd_index][0].get_child())
                return True
        return False

    # ------------------------------------------------------------------
    # 编辑器
    # ------------------------------------------------------------------

    def new_snippet(self):
        self.editing = None
        self._render("editor")

    def edit_snippet(self, snippet):
        self.editing = snippet
        self._render("editor")

    def _build_editor(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_start(8)
        header.set_margin_end(12)
        header.set_margin_top(8)
        header.add(self._icon_button("go-previous-symbolic", "返回 (Esc)", self.show_list, "‹"))
        header.add(self._label("编辑片段" if self.editing else "新建片段", "brand-title"))
        header.add(_hexpand(Gtk.Box()))
        page.add(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_start(14)
        body.set_margin_end(14)

        body.add(self._label("标题", "section"))
        self.editor_title = Gtk.Entry()
        self.editor_title.get_style_context().add_class("field")
        self.editor_title.set_placeholder_text("留空则自动取第一行")
        body.add(self.editor_title)

        body.add(self._label("内容", "section"))
        self.editor_text = Gtk.TextView()
        self.editor_text.get_style_context().add_class("editor")
        self.editor_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.editor_text.set_left_margin(10)
        self.editor_text.set_right_margin(10)
        self.editor_text.set_top_margin(8)
        self.editor_text.set_bottom_margin(8)
        self.editor_text.set_accepts_tab(True)
        self.editor_text.connect("key-press-event", self._on_editor_key)
        text_scroller = Gtk.ScrolledWindow()
        text_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_scroller.set_overlay_scrolling(True)
        text_scroller.set_size_request(-1, 196)
        text_scroller.add(self.editor_text)
        body.add(text_scroller)

        body.add(self._label("标签", "section"))
        self.editor_tags = Gtk.Entry()
        self.editor_tags.get_style_context().add_class("field")
        self.editor_tags.set_placeholder_text("用逗号分隔，例如：git, 部署")
        body.add(self.editor_tags)

        pin_wrap = Gtk.EventBox()
        pin_wrap.set_visible_window(True)
        pin_wrap.set_hexpand(True)
        pin_wrap.get_style_context().add_class("setting")
        pin_wrap.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        pin_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pin_row.set_margin_start(8)
        pin_row.set_margin_end(8)
        pin_row.set_margin_top(6)
        pin_row.set_margin_bottom(6)
        pin_row.add(self._label("置顶显示", "set-title"))
        pin_row.add(_hexpand(Gtk.Box()))
        self.editor_pin = Gtk.Switch()
        self.editor_pin.set_valign(Gtk.Align.CENTER)
        pin_row.add(self.editor_pin)
        pin_wrap.add(pin_row)
        pin_wrap.connect("button-press-event", self._on_switch_row_press, self.editor_pin)
        body.add(pin_wrap)

        page.add(body)
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        page.add(spacer)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_start(14)
        footer.set_margin_end(14)
        footer.set_margin_bottom(10)
        paste_btn = Gtk.Button(label="从剪贴板粘贴")
        paste_btn.get_style_context().add_class("ghost")
        paste_btn.set_can_focus(False)
        paste_btn.connect("clicked", lambda *_: self._paste_into_editor())
        footer.add(paste_btn)
        footer.add(_hexpand(Gtk.Box()))

        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.get_style_context().add_class("ghost")
        cancel_btn.set_can_focus(False)
        cancel_btn.connect("clicked", lambda *_: self.show_list())
        footer.add(cancel_btn)

        save_btn = Gtk.Button(label="保存")
        save_btn.get_style_context().add_class("primary")
        save_btn.set_can_focus(False)
        save_btn.connect("clicked", lambda *_: self._save_editor())
        footer.add(save_btn)
        page.add(footer)

        if self.editing:
            self.editor_title.set_text(self.editing["title"])
            buf = self.editor_text.get_buffer()
            buf.set_text(self.editing["content"])
            self.editor_tags.set_text(", ".join(self.editing["tags"]))
            self.editor_pin.set_active(bool(self.editing["pinned"]))

        self.card.add(self._wrap_toast(page))
        GLib.idle_add(self._focus_editor, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def _focus_editor(self):
        if self.mode == "editor":
            self.editor_text.grab_focus()
        return False

    def _on_editor_key(self, _widget, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if (state & Gdk.ModifierType.CONTROL_MASK) and Gdk.keyval_name(event.keyval) in ("Return", "KP_Enter"):
            self._save_editor()
            return True
        return False

    def _paste_into_editor(self):
        try:
            text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        except Exception:
            text = None
        if not text:
            self.toast("剪贴板里没有文本")
            return
        self.editor_text.get_buffer().set_text(text)
        self.toast("已粘贴剪贴板内容")

    def _save_editor(self):
        buf = self.editor_text.get_buffer()
        content = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not content:
            self.toast("内容不能为空")
            return
        title = self.editor_title.get_text().strip()
        tags = store_mod.parse_tags(self.editor_tags.get_text())
        pinned = self.editor_pin.get_active()
        if self.editing:
            self.store.update(self.editing["id"], title=title, content=content, tags=tags, pinned=pinned)
            self.toast("已保存")
        else:
            self.store.add(title, content, tags, pinned)
            self.toast("已添加")
        self.show_list()

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------

    def _build_settings(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_start(8)
        header.set_margin_end(12)
        header.set_margin_top(8)
        header.add(self._icon_button("go-previous-symbolic", "返回 (Esc)", self.show_list, "‹"))
        header.add(self._label("设置", "brand-title"))
        header.add(_hexpand(Gtk.Box()))
        page.add(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        body.set_margin_start(12)
        body.set_margin_end(12)

        body.add(self._setting_row("深色模式", "切换深色 / 浅色外观", self._theme_switch()))
        body.add(self._setting_row("复制后自动收起", "复制完成后面板自动收起", self._setting_switch("auto_collapse")))
        body.add(self._setting_row("开机自启", "登录桌面后自动显示悬浮球", self._setting_switch("autostart", self._on_autostart)) )

        body.add(Gtk.Separator(margin_top=6, margin_bottom=6))
        body.add(self._label("数据", "section"))
        data_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        data_row.set_margin_top(4)
        for label, cb in (
            ("导出备份", self._export),
            ("导入", self._import),
            ("打开目录", self._open_data_dir),
        ):
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class("ghost")
            btn.set_can_focus(False)
            btn.connect("clicked", lambda _b, f=cb: f())
            data_row.add(btn)
        body.add(data_row)

        body.add(Gtk.Separator(margin_top=8, margin_bottom=4))
        quit_btn = Gtk.Button(label="退出代码贴")
        quit_btn.get_style_context().add_class("ghost")
        quit_btn.get_style_context().add_class("danger-text")
        quit_btn.set_can_focus(False)
        quit_btn.set_halign(Gtk.Align.START)
        quit_btn.connect("clicked", lambda *_: self.emit("quit"))
        body.add(quit_btn)

        page.add(body)
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        page.add(spacer)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        footer.set_margin_start(14)
        footer.set_margin_end(14)
        footer.set_margin_bottom(12)
        footer.add(self._label(f"代码贴 CodePill v{__version__}", "brand-sub"))
        path = str(self.store.path)
        path_label = self._label(path, "brand-sub")
        path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        path_label.set_tooltip_text(path)
        footer.add(path_label)
        page.add(footer)

        self.card.add(self._wrap_toast(page))

    def _setting_row(self, title, subtitle, control):
        """整行都能点：点文字和点开关效果一样。"""
        wrapper = Gtk.EventBox()
        wrapper.set_visible_window(True)
        wrapper.set_hexpand(True)
        wrapper.get_style_context().add_class("setting")
        wrapper.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.set_margin_top(6)
        row.set_margin_bottom(6)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        texts.set_hexpand(True)
        texts.add(self._label(title, "set-title"))
        texts.add(self._label(subtitle, "set-sub"))
        row.add(texts)
        control.set_valign(Gtk.Align.CENTER)
        row.add(control)
        wrapper.add(row)

        if isinstance(control, Gtk.Switch):
            wrapper.connect("button-press-event", self._on_switch_row_press, control)
        return wrapper

    def _on_switch_row_press(self, widget, event, switch):
        """点开关以外的区域也能切换；点开关本身交给开关自己处理。"""
        if event.button != 1:
            return False
        try:
            ok, sx, sy = switch.translate_coordinates(widget, 0, 0)
        except (TypeError, ValueError):
            ok = False
        if ok:
            alloc = switch.get_allocation()
            if sx <= event.x < sx + alloc.width and sy <= event.y < sy + alloc.height:
                return False  # 点在开关本体上，交给开关处理
        switch.set_active(not switch.get_active())
        return True

    def _setting_switch(self, key: str, on_change=None):
        sw = Gtk.Switch()
        sw.set_active(bool(self.store.get_setting(key)))
        sw.set_can_focus(False)

        def _changed(widget, _pspec):
            self.store.set_setting(key, widget.get_active())
            if on_change:
                on_change(widget.get_active())

        sw.connect("notify::active", _changed)
        return sw

    def _theme_switch(self):
        sw = Gtk.Switch()
        sw.set_active(self.store.get_setting("theme") == "dark")
        sw.set_can_focus(False)

        def _changed(widget, _pspec):
            name = "dark" if widget.get_active() else "light"
            self.store.set_setting("theme", name)
            theme.apply(name)

        sw.connect("notify::active", _changed)
        return sw

    def _on_autostart(self, enabled: bool):
        try:
            store_mod.set_autostart(enabled)
        except OSError as exc:
            self.toast(f"设置失败：{exc}")

    def _setup_dialog(self, dialog: Gtk.Dialog):
        """对话框不要躲到「始终置顶」的面板后面。"""
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.set_modal(True)
        try:
            dialog.set_keep_above(True)
        except Exception:
            pass

    def _open_data_dir(self):
        try:
            Gio.AppInfo.launch_default_for_uri(self.store.path.parent.as_uri(), None)
        except Exception as exc:
            self.toast(f"无法打开目录：{exc}")

    def _export(self):
        dialog = Gtk.FileChooserDialog(
            title="导出代码贴备份",
            transient_for=self.get_toplevel() if isinstance(self.get_toplevel(), Gtk.Window) else None,
            action=Gtk.FileChooserAction.SAVE,
        )
        self._setup_dialog(dialog)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(time.strftime("codepill-%Y%m%d.json"))
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL, "导出", Gtk.ResponseType.ACCEPT)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            try:
                count = self.store.export_to(dialog.get_filename())
                self.toast(f"已导出 {count} 条")
            except Exception as exc:
                self.toast(f"导出失败：{exc}")
        dialog.destroy()

    def _import(self):
        dialog = Gtk.FileChooserDialog(
            title="导入代码贴备份",
            transient_for=self.get_toplevel() if isinstance(self.get_toplevel(), Gtk.Window) else None,
            action=Gtk.FileChooserAction.OPEN,
        )
        self._setup_dialog(dialog)
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL, "导入", Gtk.ResponseType.ACCEPT)
        filt = Gtk.FileFilter()
        filt.set_name("JSON 文件")
        filt.add_pattern("*.json")
        dialog.add_filter(filt)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            try:
                added, skipped = self.store.import_from(dialog.get_filename())
                self._rebuild_chips()
                self._refresh_list()
                self.toast(f"导入 {added} 条，跳过 {skipped} 条")
            except Exception as exc:
                self.toast(f"导入失败：{exc}")
        dialog.destroy()

    # ------------------------------------------------------------------
    # 提示条
    # ------------------------------------------------------------------

    def toast(self, text: str, action_label: str | None = None, action_cb=None, timeout: int = 1800):
        if self.mode == "pill" or not hasattr(self, "_toast_revealer"):
            return
        self._toast_label.set_text(text)
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
            self._toast_timer = 0
        if action_label and action_cb:
            self._toast_button.set_label(action_label)
            self._toast_button.set_no_show_all(False)
            self._toast_button.show()
            try:
                self._toast_button.disconnect(self._toast_action)
            except (TypeError, AttributeError):
                pass
            self._toast_action = self._toast_button.connect("clicked", lambda *_: action_cb())
            timeout = max(timeout, 4000)
            self._set_toast_pass_through(False)
        else:
            self._toast_button.hide()
            self._set_toast_pass_through(True)
        self._toast_revealer.set_reveal_child(True)
        self._toast_timer = GLib.timeout_add(timeout, self._hide_toast)

    def _set_toast_pass_through(self, enabled: bool):
        overlay = getattr(self, "_toast_overlay", None)
        if overlay is None:
            return
        try:
            overlay.set_overlay_pass_through(self._toast_revealer, enabled)
        except AttributeError:
            pass

    def _hide_toast(self):
        self._toast_timer = 0
        self._toast_revealer.set_reveal_child(False)
        self._set_toast_pass_through(True)
        return False

    def _hide_toast_now(self):
        if getattr(self, "_toast_revealer", None) is not None:
            self._toast_revealer.set_reveal_child(False)
            self._set_toast_pass_through(True)
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
            self._toast_timer = 0

    # ------------------------------------------------------------------
    # 状态切换
    # ------------------------------------------------------------------

    def show_list(self):
        self.active_tag = self.active_tag if self.active_tag in self.store.tags() else None
        self._render("list")

    def show_settings(self):
        self._render("settings")

    def collapse(self):
        if self.mode == "pill":
            return
        self.search_text = ""
        self.active_tag = None
        self._render("pill")
        self.emit("collapse")

    def toggle(self):
        if self.mode == "pill":
            self.show_list()
        else:
            self.collapse()

    # ------------------------------------------------------------------
    # 剪贴板
    # ------------------------------------------------------------------

    @staticmethod
    def _default_clipboard(text: str) -> bool:
        try:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(text, -1)
            clipboard.store()
            return True
        except Exception:
            return False


class PillWindow(Gtk.Window):
    """把 UI 放进一个无边框、始终置顶、背景透明的窗口。"""

    def __init__(self, store: store_mod.Store):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.store = store
        self.set_name("codepill-window")
        self.set_wmclass("codepill", "CodePill")
        self.set_role("codepill")
        self.set_decorated(False)
        # 固定尺寸窗口：GTK 会同步更新尺寸提示，resize() 在各窗口管理器上都可靠。
        # 万一某个 WM 没有跟随（_check_size 会检测到），再退回可调整大小。
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.keep_above = True
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_accept_focus(True)
        self.set_focus_on_map(True)
        try:
            self.set_sticky(True)
        except Exception:
            pass
        self.connect("delete-event", lambda *_: True)  # 只能从设置里退出

        # 透明背景
        screen = self.get_screen()
        visual = screen.get_rgba_visual() if screen else None
        self._transparent = visual is not None
        if visual is not None:
            self.set_visual(visual)
            self.set_app_paintable(True)
        else:
            print("[codepill] 没有合成器，透明效果不可用", flush=True)
            self.get_style_context().add_class("opaque")

        self.ui = UI(store)
        self.ui.connect("request-size", self._on_request_size)
        self.ui.connect("collapse", lambda *_: self._on_collapsed())
        self.ui.connect("quit", lambda *_: self._quit())
        self.ui.connect("move-begin", self._on_drag_begin)
        self.ui.connect("move-update", self._on_drag_update)
        self.ui.connect("move-end", self._on_drag_end)

        self.add(self.ui)
        self._drag_origin = (0, 0)
        self._shape_source = 0
        self._shape_retries = 0
        self._load_geometry()

        # 让窗口的鼠标响应区域和可见卡片保持一致，透明边距里点击直接穿透到桌面
        self.connect("realize", lambda *_: self._schedule_input_shape())
        self.connect("map-event", lambda *_: self._schedule_input_shape())
        self.connect("size-allocate", lambda *_: self._schedule_input_shape())

    # -- 几何 -----------------------------------------------------------

    def _workarea(self):
        display = self.get_display()
        monitor = display.get_primary_monitor()
        try:
            monitor = display.get_monitor_at_point(self._anchor[0], self._anchor[1]) or monitor
        except Exception:
            pass
        area = monitor.get_workarea()
        if area.width <= 0 or area.height <= 0:
            area = monitor.get_geometry()
        return area

    def _load_geometry(self):
        anchor = self.store.get_setting("anchor")
        if not anchor or len(anchor) != 2:
            area = self.get_display().get_primary_monitor().get_workarea()
            anchor = [area.x + area.width - 30, area.y + 64]
        self._anchor = [int(anchor[0]), int(anchor[1])]
        self._apply_geometry()

    def _on_request_size(self, _ui, width, height):
        self._size = (width, height)
        self._apply_geometry()

    def _apply_geometry(self):
        width, height = getattr(self, "_size", CARD_SIZES["pill"])
        area = self._workarea()
        height = min(height, area.height - 96)
        win_w = width + PAD * 2
        win_h = height + PAD * 2
        x = int(round(self._anchor[0] - win_w + PAD))
        y = int(round(self._anchor[1] - PAD))
        x = max(area.x + 6, min(x, area.x + area.width - win_w - 6))
        y = max(area.y + 6, min(y, area.y + area.height - win_h - 6))
        self.resize(win_w, win_h)
        self.move(x, y)
        self._window_origin = (x, y)
        self._schedule_input_shape()
        GLib.timeout_add(150, self._check_size, win_w, win_h)

    def _check_size(self, want_w: int, want_h: int):
        """某些窗口管理器会忽略对固定尺寸窗口的 resize，检测到就放开限制重试。"""
        got_w, got_h = self.get_size()
        if (got_w, got_h) != (want_w, want_h):
            self.set_resizable(True)
            self.resize(want_w, want_h)
        return False

    # -- 鼠标可交互区域 -------------------------------------------------

    def _schedule_input_shape(self):
        if self._shape_source:
            return
        self._shape_source = GLib.idle_add(self._apply_input_shape)

    def _apply_input_shape(self):
        self._shape_source = 0
        win = self.get_window()
        if win is None or not win.is_viewable():
            return False
        width, height = getattr(self, "_size", CARD_SIZES["pill"])
        win_w, win_h = self.get_size()
        if abs(win_w - (width + PAD * 2)) > 2 or abs(win_h - (height + PAD * 2)) > 2:
            # 窗口尺寸还没跟上（异步 resize），稍后重试，避免用旧尺寸设错区域
            if self._shape_retries < 20:
                self._shape_retries += 1
                self._shape_source = GLib.timeout_add(40, self._apply_input_shape)
            return False
        self._shape_retries = 0
        try:
            win.input_shape_combine_region(self._card_input_region(width, height), 0, 0)
        except Exception:
            pass
        return False

    def _card_input_region(self, width: int, height: int):
        """可见卡片（含圆角）的 cairo.Region，用于限制鼠标响应范围。"""
        radius = height / 2.0 if self.ui.mode == "pill" else 18.0
        radius = max(0.0, min(radius, width / 2.0, height / 2.0))
        x0 = float(PAD)
        y0 = float(PAD)
        region = cairo.Region(
            cairo.RectangleInt(int(round(x0)), int(round(y0 + radius)),
                               int(round(width)), int(round(height - radius * 2)))
        )
        for i in range(int(round(radius))):
            dy = radius - (i + 0.5)
            inset = radius - math.sqrt(max(0.0, radius * radius - dy * dy))
            left = int(round(x0 + inset))
            row_w = int(round(width - inset * 2))
            if row_w <= 0:
                continue
            top = int(round(y0)) + i
            bottom = int(round(y0 + height)) - 1 - i
            region.union(cairo.Region(cairo.RectangleInt(left, top, row_w, 1)))
            region.union(cairo.Region(cairo.RectangleInt(left, bottom, row_w, 1)))
        return region

    def _save_anchor(self):
        x, y = self.get_position()
        win_w, _ = self.get_size()
        self._anchor = [int(x + win_w - PAD), int(y + PAD)]
        self.store.set_setting("anchor", self._anchor)

    # -- 拖动 -----------------------------------------------------------

    def _on_drag_begin(self, _ui):
        self._drag_origin = self.get_position()

    def _on_drag_update(self, _ui, dx, dy):
        self.move(self._drag_origin[0] + dx, self._drag_origin[1] + dy)

    def _on_drag_end(self, _ui):
        self._save_anchor()

    # -- 状态 -----------------------------------------------------------

    def _on_collapsed(self):
        self._save_anchor()

    def expand(self):
        if self.ui.mode == "pill":
            self.ui.show_list()

    def _quit(self):
        self.store.save()
        app = Gtk.Application.get_default()
        if app is not None:
            app.quit()
        else:
            Gtk.main_quit()


def _settle(limit: int = 200) -> None:
    """把主循环跑到空闲，保证布局 / 尺寸计算都完成。"""
    for _ in range(limit):
        if not Gtk.main_iteration_do(False):
            break


def render_preview(store: store_mod.Store, mode: str = "list", scale: float = 1.0):
    """离屏渲染当前界面，返回带透明通道的 GdkPixbuf（开发/截图用）。"""
    from gi.repository import GdkPixbuf

    ui = UI(store)
    ui._render(mode)
    _settle()
    offscreen = Gtk.OffscreenWindow()
    offscreen.add(ui)
    offscreen.show_all()
    _settle()
    pixbuf = offscreen.get_pixbuf()
    if scale != 1.0:
        w = int(pixbuf.get_width() * scale)
        h = int(pixbuf.get_height() * scale)
        pixbuf = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    return pixbuf
