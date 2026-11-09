#!/usr/bin/env python3
"""界面逻辑测试（需要图形界面；没有 DISPLAY 时自动跳过）。

运行：python3 -m unittest tests.test_ui -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import gi  # noqa: E402

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from codepill import store as store_mod, theme, ui  # noqa: E402

_HAS_DISPLAY = Gtk.init_check([])[0]


@unittest.skipUnless(_HAS_DISPLAY, "需要图形界面（DISPLAY）")
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        theme.apply("dark")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = store_mod.Store(Path(self.tmp.name) / "snippets.json")
        self.store.set_setting("auto_collapse", False)
        self.copied: list[str] = []
        self.ui = ui.UI(self.store, clipboard_writer=self._fake_clipboard)
        self.ui.show_list()
        self._pump()

    def tearDown(self):
        self.ui.destroy()
        self.tmp.cleanup()

    def _fake_clipboard(self, text):
        self.copied.append(text)
        return True

    def _pump(self, times: int = 5):
        for _ in range(times):
            while Gtk.events_pending():
                Gtk.main_iteration()

    # ------------------------------------------------------------------

    def test_initial_rows_match_store(self):
        self.assertEqual(len(self.ui._rows), len(self.store.snippets()))
        self.assertEqual(self.ui.mode, "list")

    def test_copy_puts_content_on_clipboard(self):
        snippet = self.ui._rows[0][1]
        self.ui._copy(snippet)
        self.assertEqual(self.copied[-1], snippet["content"])
        self.assertEqual(self.store.get(snippet["id"])["uses"], 1)
        self.assertTrue(self.ui._toast_revealer.get_reveal_child())

    def test_click_row_copies(self):
        row, snippet = self.ui._rows[2]
        widget = row.get_child()

        class FakeEvent:
            button = 1
            x_root = 0
            y_root = 0

        self.ui._on_row_press(widget, FakeEvent(), snippet)
        self.assertEqual(self.copied[-1], snippet["content"])

    def test_keyboard_navigation_and_enter(self):
        self.ui._highlight_row(1)
        self.assertEqual(self.ui._kbd_index, 1)
        self.ui._highlight_row(0)

        class FakeKey:
            keyval = ui.Gdk.KEY_Return
            state = 0

        self.ui._on_key_press(self.ui, FakeKey())
        self.assertEqual(self.copied[-1], self.ui._rows[0][1]["content"])

    def test_search_filters_rows(self):
        self.ui.search_entry.set_text("docker")
        self._pump()
        titles = [s["title"] for _r, s in self.ui._rows]
        self.assertIn("Docker 清理", titles)
        self.assertLess(len(self.ui._rows), len(self.store.snippets()))

        self.ui.search_entry.set_text("绝对不存在的关键字")
        self._pump()
        self.assertEqual(len(self.ui._rows), 0)
        self.assertEqual(self.ui.page_stack.get_visible_child_name(), "empty")

    def test_tag_filter(self):
        self.ui._set_tag("git")
        self._pump()
        self.assertTrue(all("git" in s["tags"] for _r, s in self.ui._rows))
        self.ui._set_tag("git")  # 再点一次取消
        self._pump()
        self.assertIsNone(self.ui.active_tag)
        self.assertEqual(len(self.ui._rows), len(self.store.snippets()))

    def test_empty_state_for_filtered_search(self):
        self.ui.search_entry.set_text("绝对没有这个")
        self._pump()
        self.assertEqual(self.ui.page_stack.get_visible_child_name(), "empty")
        self.assertEqual(self.ui._empty_title.get_text(), "没有匹配的片段")
        self.assertEqual(self.ui._empty_btn.get_label(), "清除筛选")
        self.ui._on_empty_action()
        self._pump()
        self.assertEqual(self.ui.search_text, "")
        self.assertEqual(len(self.ui._rows), len(self.store.snippets()))

    def test_collapse_clears_filters(self):
        self.ui.search_entry.set_text("git")
        self._pump()
        self.ui.collapse()
        self._pump()
        self.assertEqual(self.ui.mode, "pill")
        self.assertEqual(self.ui.search_text, "")
        self.assertIsNone(self.ui.active_tag)

    def test_enter_in_search_copies_first_match(self):
        self.ui.search_entry.set_text("docker")
        self._pump()
        first = self.ui._rows[0][1]
        self.ui._copy_first_match(self.ui.search_entry)
        self.assertEqual(self.copied[-1], first["content"])

    def test_add_snippet_via_editor(self):
        before = len(self.store.snippets())
        self.ui.new_snippet()
        self._pump()
        self.assertEqual(self.ui.mode, "editor")

        self.ui.editor_title.set_text("测试命令")
        self.ui.editor_text.get_buffer().set_text("sudo systemctl restart nginx")
        self.ui.editor_tags.set_text("nginx, 运维")
        self.ui.editor_pin.set_active(True)
        self.ui._save_editor()
        self._pump()

        self.assertEqual(self.ui.mode, "list")
        self.assertEqual(len(self.store.snippets()), before + 1)
        added = next(s for s in self.store.snippets() if s["title"] == "测试命令")
        self.assertEqual(added["tags"], ["nginx", "运维"])
        self.assertTrue(added["pinned"])
        self.assertEqual(added["content"], "sudo systemctl restart nginx")

    def test_empty_content_is_rejected(self):
        self.ui.new_snippet()
        self._pump()
        before = len(self.store.snippets())
        self.ui.editor_text.get_buffer().set_text("   ")
        self.ui._save_editor()
        self._pump()
        self.assertEqual(self.ui.mode, "editor")
        self.assertEqual(len(self.store.snippets()), before)

    def test_edit_existing_snippet(self):
        snippet = self.store.snippets()[0]
        self.ui.edit_snippet(snippet)
        self._pump()
        self.assertEqual(self.ui.mode, "editor")
        self.assertEqual(self.ui.editor_title.get_text(), snippet["title"])
        self.ui.editor_title.set_text("改过的标题")
        self.ui._save_editor()
        self._pump()
        self.assertEqual(self.store.get(snippet["id"])["title"], "改过的标题")

    def test_delete_and_undo(self):
        snippet = self.store.snippets()[0]
        count = len(self.store.snippets())
        self.ui._delete(snippet)
        self._pump()
        self.assertEqual(len(self.store.snippets()), count - 1)
        self.ui._undo_delete(snippet)
        self._pump()
        self.assertEqual(len(self.store.snippets()), count)
        self.assertIsNotNone(self.store.get(snippet["id"]))

    def test_pin_moves_to_top(self):
        target = next(s for s in self.store.snippets() if not s["pinned"])
        self.ui._toggle_pin(target)
        self._pump()
        self.assertEqual(self.store.snippets()[0]["id"], target["id"])

    def test_setting_row_click_toggles_switch(self):
        self.ui.show_settings()
        self._pump()

        def walk(widget):
            if hasattr(widget, "get_children"):
                for child in widget.get_children():
                    yield child
                    yield from walk(child)

        switches = [w for w in walk(self.ui.card) if isinstance(w, Gtk.Switch)]
        self.assertEqual(len(switches), 3)
        sw = switches[1]  # 复制后自动收起（不会写真实家目录）
        wrapper = sw.get_parent().get_parent()
        before = sw.get_active()

        class Event:
            button = 1
            x = 4
            y = 4

        handled = self.ui._on_switch_row_press(wrapper, Event(), sw)
        self.assertTrue(handled)
        self.assertNotEqual(sw.get_active(), before)

        # 再点一次能切回去
        self.ui._on_switch_row_press(wrapper, Event(), sw)
        self.assertEqual(sw.get_active(), before)

    def test_mode_cycle(self):
        self.ui.show_settings()
        self._pump()
        self.assertEqual(self.ui.mode, "settings")
        self.ui.show_list()
        self._pump()
        self.assertEqual(self.ui.mode, "list")
        self.ui.collapse()
        self._pump()
        self.assertEqual(self.ui.mode, "pill")

    def test_size_tracks_row_count(self):
        many = [self.store.add(f"命令 {i}", f"echo {i}") for i in range(30)]
        self.ui.show_list()
        self._pump(20)
        self.assertGreater(self.ui.get_preferred_height()[1], 400)
        for item in many:
            self.store.delete(item["id"])
        self.ui.show_list()
        self._pump(20)
        # 条目减少后，卡片高度应该回落，且不会无限变高
        self.assertLessEqual(self.ui.get_preferred_height()[1], 700)

    def test_real_clipboard(self):
        cb = Gtk.Clipboard.get(ui.Gdk.SELECTION_CLIPBOARD)
        ok = ui.UI._default_clipboard("代码贴 clipboard test")
        self.assertTrue(ok)
        self.assertEqual(cb.wait_for_text(), "代码贴 clipboard test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
