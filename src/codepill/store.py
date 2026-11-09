"""数据层：代码片段与设置的持久化。

所有内容保存在 ~/.config/codepill/snippets.json，采用「写临时文件 + 原子替换」
的方式落盘，避免程序崩溃时损坏数据文件。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

APP_ID = "codepill"
APP_NAME = "代码贴"

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------


def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base)


def config_dir() -> Path:
    return config_home() / APP_ID


def default_data_path() -> Path:
    return config_dir() / "snippets.json"


def autostart_path() -> Path:
    return config_home() / "autostart" / f"{APP_ID}.desktop"


def _now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# 默认设置与示例数据
# ---------------------------------------------------------------------------

SETTINGS_DEFAULTS = {
    "theme": "dark",          # dark | light
    "auto_collapse": True,    # 复制后自动收起面板
    "autostart": True,        # 开机自启
    "anchor": None,           # [卡片右边缘 x, 卡片顶部 y]
    "last_tag": None,         # 上次选择的标签过滤器
}

SAMPLE_SNIPPETS = [
    {
        "title": "更新系统",
        "content": "sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y",
        "tags": ["系统", "apt"],
        "pinned": True,
    },
    {
        "title": "查看磁盘占用",
        "content": "df -hT -x tmpfs -x devtmpfs | sort -k5 -rh\ndu -sh * 2>/dev/null | sort -rh | head -10",
        "tags": ["系统", "磁盘"],
        "pinned": False,
    },
    {
        "title": "谁占用了端口",
        "content": "ss -tlnp | grep -E ':(8080|3000|5173)'\nlsof -i :8080",
        "tags": ["系统", "网络"],
        "pinned": False,
    },
    {
        "title": "查找大文件",
        "content": "find . -type f -size +200M -printf '%s\\t%p\\n' | sort -rn | head -20",
        "tags": ["文件"],
        "pinned": False,
    },
    {
        "title": "Git 撤销最近一次提交",
        "content": "git reset --soft HEAD~1      # 保留改动\ngit commit --amend -m \"新的提交说明\"",
        "tags": ["git"],
        "pinned": False,
    },
    {
        "title": "Docker 清理",
        "content": "docker system df\ndocker system prune -af --volumes",
        "tags": ["docker"],
        "pinned": False,
    },
    {
        "title": "解压 tar.gz",
        "content": "tar -xzvf archive.tar.gz -C ./target-dir",
        "tags": ["文件"],
        "pinned": False,
    },
    {
        "title": "查看系统信息",
        "content": "lsb_release -a\nuname -a\nfree -h\nlscpu | head -20",
        "tags": ["系统"],
        "pinned": False,
    },
]


def _make_snippet(title: str, content: str, tags=None, pinned: bool = False) -> dict:
    ts = _now()
    return {
        "id": new_id(),
        "title": title,
        "content": content,
        "tags": list(tags or []),
        "pinned": bool(pinned),
        "created": ts,
        "used": ts,
        "uses": 0,
    }


def sample_snippets() -> list[dict]:
    return [_make_snippet(s["title"], s["content"], s["tags"], s["pinned"]) for s in SAMPLE_SNIPPETS]


def parse_tags(text: str) -> list[str]:
    """把 "git, docker、运维" 解析成去重后的标签列表。"""
    raw = (text or "").replace("，", ",").replace("、", ",").replace(";", ",")
    out: list[str] = []
    for part in raw.replace(",", " ").split():
        tag = part.strip().lstrip("#")
        if tag and tag not in out:
            out.append(tag)
    return out


def title_from_content(content: str, limit: int = 24) -> str:
    for line in (content or "").splitlines():
        line = line.strip()
        if line:
            return line[:limit] + ("…" if len(line) > limit else "")
    return "未命名片段"


def sort_snippets(items: list[dict]) -> list[dict]:
    """置顶优先，其次最近使用，最后按创建时间倒序。"""
    return sorted(
        items,
        key=lambda s: (not s.get("pinned"), -float(s.get("used") or 0), -float(s.get("created") or 0)),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    """代码片段仓库。所有修改都会立即写盘。"""

    def __init__(self, path: os.PathLike | str | None = None):
        self.path = Path(path) if path else default_data_path()
        self.data: dict = {"version": 1, "settings": dict(SETTINGS_DEFAULTS), "snippets": []}
        self.load()

    # -- 读写 ---------------------------------------------------------------

    def load(self) -> None:
        if not self.path.exists():
            self.data["snippets"] = sample_snippets()
            self.save()
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("数据文件格式不正确")
        except (OSError, ValueError) as exc:
            self._backup_broken_file(exc)
            self.data["snippets"] = sample_snippets()
            self.save()
            return

        settings = dict(SETTINGS_DEFAULTS)
        settings.update({k: v for k, v in (raw.get("settings") or {}).items() if k in SETTINGS_DEFAULTS})
        if settings["theme"] not in ("dark", "light"):
            settings["theme"] = "dark"
        self.data = {
            "version": 1,
            "settings": settings,
            "snippets": [self._normalize(s) for s in (raw.get("snippets") or []) if isinstance(s, dict)],
        }
        self.data["snippets"] = [s for s in self.data["snippets"] if s["content"].strip()]

    def _backup_broken_file(self, exc: Exception) -> None:
        try:
            backup = self.path.with_name(f"snippets.broken-{int(_now())}.json")
            shutil.copy2(self.path, backup)
            print(f"[codepill] 数据文件损坏（{exc}），已备份到 {backup}", flush=True)
        except OSError:
            pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[codepill] 无法创建数据目录：{exc}", flush=True)
            return
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(prefix=".snippets-", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            print(f"[codepill] 保存数据失败：{exc}", flush=True)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- 规范化 -------------------------------------------------------------

    @staticmethod
    def _normalize(raw: dict) -> dict:
        content = str(raw.get("content") or "").replace("\r\n", "\n")
        title = str(raw.get("title") or "").strip() or title_from_content(content)
        tags = raw.get("tags") or []
        if isinstance(tags, str):
            tags = parse_tags(tags)
        return {
            "id": str(raw.get("id") or new_id()),
            "title": title,
            "content": content,
            "tags": [str(t) for t in tags if str(t).strip()],
            "pinned": bool(raw.get("pinned")),
            "created": float(raw.get("created") or _now()),
            "used": float(raw.get("used") or 0),
            "uses": int(raw.get("uses") or 0),
        }

    # -- 设置 ---------------------------------------------------------------

    @property
    def settings(self) -> dict:
        return self.data["settings"]

    def get_setting(self, key: str, default=None):
        return self.settings.get(key, SETTINGS_DEFAULTS.get(key, default))

    def set_setting(self, key: str, value) -> None:
        self.settings[key] = value
        self.save()

    # -- 片段 ---------------------------------------------------------------

    def snippets(self) -> list[dict]:
        return sort_snippets(self.data["snippets"])

    def get(self, snippet_id: str) -> dict | None:
        return next((s for s in self.data["snippets"] if s["id"] == snippet_id), None)

    def add(self, title: str, content: str, tags=None, pinned: bool = False) -> dict:
        snippet = _make_snippet(
            (title or "").strip() or title_from_content(content),
            (content or "").strip(),
            parse_tags(tags) if isinstance(tags, str) else tags,
            pinned,
        )
        self.data["snippets"].append(snippet)
        self.save()
        return snippet

    def update(self, snippet_id: str, **fields) -> dict | None:
        snippet = self.get(snippet_id)
        if snippet is None:
            return None
        for key in ("title", "content", "tags", "pinned"):
            if key in fields and fields[key] is not None:
                value = fields[key]
                if key == "tags" and isinstance(value, str):
                    value = parse_tags(value)
                if key == "title":
                    value = str(value).strip() or title_from_content(snippet["content"])
                snippet[key] = value
        self.save()
        return snippet

    def delete(self, snippet_id: str) -> bool:
        before = len(self.data["snippets"])
        self.data["snippets"] = [s for s in self.data["snippets"] if s["id"] != snippet_id]
        if len(self.data["snippets"]) != before:
            self.save()
            return True
        return False

    def restore(self, snippet: dict) -> None:
        """把删除的片段放回去（撤销用）。"""
        if any(s["id"] == snippet["id"] for s in self.data["snippets"]):
            return
        self.data["snippets"].append(self._normalize(dict(snippet)))
        self.save()

    def toggle_pin(self, snippet_id: str) -> bool | None:
        snippet = self.get(snippet_id)
        if snippet is None:
            return None
        snippet["pinned"] = not snippet["pinned"]
        self.save()
        return snippet["pinned"]

    def record_use(self, snippet_id: str) -> None:
        snippet = self.get(snippet_id)
        if snippet is None:
            return
        snippet["used"] = _now()
        snippet["uses"] = int(snippet.get("uses") or 0) + 1
        self.save()

    def tags(self) -> list[str]:
        seen: list[str] = []
        for snippet in self.data["snippets"]:
            for tag in snippet["tags"]:
                if tag not in seen:
                    seen.append(tag)
        return seen

    def query(self, text: str = "", tag: str | None = None) -> list[dict]:
        needle = (text or "").strip().lower()
        result = []
        for snippet in self.data["snippets"]:
            if tag and tag not in snippet["tags"]:
                continue
            if needle:
                haystack = " ".join(
                    [snippet["title"], snippet["content"], " ".join(snippet["tags"])]
                ).lower()
                if needle not in haystack:
                    continue
            result.append(snippet)
        return sort_snippets(result)

    # -- 导入导出 -----------------------------------------------------------

    def export_to(self, path: os.PathLike | str) -> int:
        payload = {
            "version": 1,
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "snippets": self.snippets(),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return len(payload["snippets"])

    def import_from(self, path: os.PathLike | str) -> tuple[int, int]:
        """合并导入；返回 (新增数量, 跳过数量)。完全相同的内容会跳过。"""
        raw = json.loads(Path(path).read_text("utf-8"))
        items = raw.get("snippets") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            raise ValueError("无法识别的文件格式")
        existing = {(s["title"], s["content"]) for s in self.data["snippets"]}
        added = skipped = 0
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            snippet = self._normalize(item)
            if not snippet["content"].strip():
                skipped += 1
                continue
            key = (snippet["title"], snippet["content"])
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            self.data["snippets"].append(snippet)
            added += 1
        if added:
            self.save()
        return added, skipped


# ---------------------------------------------------------------------------
# 开机自启
# ---------------------------------------------------------------------------


AUTOSTART_TEMPLATE = """[Desktop Entry]
Type=Application
Name=代码贴 CodePill
Comment=悬浮在桌面的代码/命令速取工具
Exec={exec_path}
Icon=codepill
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=2
StartupNotify=false
Hidden={hidden}
"""


def set_autostart(enabled: bool, exec_path: str = "/usr/bin/codepill") -> None:
    path = autostart_path()
    if not enabled:
        # 系统级 /etc/xdg/autostart 里也有一份，用用户级 Hidden=true 覆盖它
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            AUTOSTART_TEMPLATE.format(exec_path=exec_path, hidden="true"), "utf-8"
        )
        return
    if path.exists():
        path.unlink()


def autostart_enabled() -> bool:
    path = autostart_path()
    if path.exists():
        try:
            text = path.read_text("utf-8")
        except OSError:
            return False
        return "Hidden=true" not in text
    # 没有用户级覆盖时，以 /etc/xdg/autostart 中是否安装为准
    return Path("/etc/xdg/autostart/codepill.desktop").exists()
