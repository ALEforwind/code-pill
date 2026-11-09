#!/usr/bin/env python3
"""数据层单元测试：python3 -m unittest discover -s tests"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from codepill import store as store_mod  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "snippets.json"
        self.store = store_mod.Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_seeds_samples(self):
        self.assertTrue(self.path.exists())
        self.assertGreaterEqual(len(self.store.snippets()), 5)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_add_update_delete_restore(self):
        snippet = self.store.add("部署命令", "docker compose up -d", "docker, 部署", False)
        self.assertEqual(snippet["tags"], ["docker", "部署"])
        self.assertEqual(snippet["title"], "部署命令")

        self.store.update(snippet["id"], title="部署", content="docker compose up -d --build")
        self.assertEqual(self.store.get(snippet["id"])["title"], "部署")

        self.assertTrue(self.store.toggle_pin(snippet["id"]))
        self.assertTrue(self.store.get(snippet["id"])["pinned"])

        self.assertTrue(self.store.delete(snippet["id"]))
        self.assertIsNone(self.store.get(snippet["id"]))
        self.store.restore(snippet)
        self.assertIsNotNone(self.store.get(snippet["id"]))

    def test_title_falls_back_to_content(self):
        snippet = self.store.add("", "  git status  \n")
        self.assertEqual(snippet["title"], "git status")
        self.assertEqual(snippet["content"], "git status")

    def test_search_and_tag_filter(self):
        self.store.add("专用排查", "ss -tlnp | grep 9999", "网络")
        self.assertEqual(len(self.store.query("9999")), 1)
        self.assertEqual(len(self.store.query("专用排查")), 1)
        self.assertEqual(len(self.store.query("", "网络")), 2)  # 示例数据里也有一条
        self.assertEqual(self.store.query("不存在的关键词"), [])

    def test_sort_pinned_first(self):
        old = self.store.add("普通", "echo hi")
        self.store.add("置顶", "echo top", pinned=True)
        ordered = self.store.snippets()
        self.assertEqual(ordered[0]["title"], "置顶")
        self.assertIn(old["id"], [s["id"] for s in ordered])

    def test_record_use(self):
        snippet = self.store.snippets()[0]
        before = snippet["uses"]
        self.store.record_use(snippet["id"])
        self.assertEqual(self.store.get(snippet["id"])["uses"], before + 1)

    def test_export_import_roundtrip(self):
        out = Path(self.tmp.name) / "backup.json"
        count = self.store.export_to(out)
        self.assertEqual(count, len(self.store.snippets()))

        other_path = Path(self.tmp.name) / "other.json"
        other = store_mod.Store(other_path)
        other.data["snippets"] = []
        other.save()
        added, skipped = other.import_from(out)
        self.assertEqual(added, count)
        self.assertEqual(skipped, 0)

        # 再导入一次应该全部跳过
        added2, skipped2 = other.import_from(out)
        self.assertEqual(added2, 0)
        self.assertEqual(skipped2, count)

    def test_corrupt_file_is_backed_up(self):
        self.path.write_text("{ not json", "utf-8")
        recovered = store_mod.Store(self.path)
        self.assertGreaterEqual(len(recovered.snippets()), 5)
        backups = list(self.path.parent.glob("snippets.broken-*.json"))
        self.assertEqual(len(backups), 1)

    def test_settings_persist(self):
        self.store.set_setting("theme", "light")
        self.store.set_setting("anchor", [100, 200])
        again = store_mod.Store(self.path)
        self.assertEqual(again.get_setting("theme"), "light")
        self.assertEqual(again.get_setting("anchor"), [100, 200])

    def test_parse_tags(self):
        self.assertEqual(store_mod.parse_tags("git, docker、运维， git"), ["git", "docker", "运维"])
        self.assertEqual(store_mod.parse_tags(""), [])

    def test_import_rejects_garbage(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text(json.dumps({"hello": 1}), "utf-8")
        with self.assertRaises(ValueError):
            self.store.import_from(bad)

    def test_autostart_file(self):
        old_home = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(Path(self.tmp.name) / "cfg")
        try:
            store_mod.set_autostart(False)
            target = Path(os.environ["XDG_CONFIG_HOME"]) / "autostart" / "codepill.desktop"
            self.assertTrue(target.exists())
            self.assertIn("Hidden=true", target.read_text("utf-8"))
            self.assertFalse(store_mod.autostart_enabled())
            store_mod.set_autostart(True)
            self.assertFalse(target.exists())
        finally:
            if old_home is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old_home


if __name__ == "__main__":
    unittest.main(verbosity=2)
