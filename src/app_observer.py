"""前台应用使用统计（Tai 式 AppObserver 的 Python 实现）

机制：
- 每秒轮询 Win32 GetForegroundWindow，取前台进程名 / 窗口标题
- 应用切换时结束旧会话、开始新会话，会话落 SQLite（data/app_usage.db）
- GetLastInputInfo 离开检测：超时无输入则结束会话并暂停统计，回来时恢复
- 维护 app_meta（应用别名 / 类别映射）：别名来源 = 配置 > 内置表 > 窗口标题学习 > 进程名
- 当前状态写 data/app_state.json，供悬浮面板读取（独立 ui 模式也能显示）

仅 Windows 有效；其他平台所有方法安全降级（start 不启动、get_current 返回 None）。
"""
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    try:
        import psutil
        PSUTIL_AVAILABLE = True
    except ImportError:
        PSUTIL_AVAILABLE = False

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


# 已知应用别名表（进程名不区分大小写匹配，key 一律小写）
KNOWN_ALIASES = {
    "wechat.exe": "微信",
    "weixin.exe": "微信",
    "qq.exe": "QQ",
    "tim.exe": "TIM",
    "dingtalk.exe": "钉钉",
    "code.exe": "VS Code",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "steam.exe": "Steam",
    "explorer.exe": "资源管理器",
    "notepad.exe": "记事本",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "wps.exe": "WPS",
    "et.exe": "WPS 表格",
    "wpp.exe": "WPS 演示",
    "obs64.exe": "OBS",
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ 音乐",
    "potplayermini64.exe": "PotPlayer",
    "potplayermini.exe": "PotPlayer",
    "bilibili.exe": "哔哩哔哩",
    "feishu.exe": "飞书",
    "wxwork.exe": "企业微信",
}

# 不参与统计的前台进程（锁屏等系统界面）
IGNORED_APPS = {"lockapp.exe"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    app TEXT NOT NULL,
    title TEXT,
    start TEXT NOT NULL,
    duration REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
CREATE TABLE IF NOT EXISTS app_meta(
    app TEXT PRIMARY KEY,
    alias TEXT,
    category TEXT,
    cat_counts TEXT NOT NULL DEFAULT '{}',
    updated TEXT
);
"""


def _idle_seconds() -> float:
    """距最后一次键盘/鼠标输入的秒数（失败返回 0）。"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(millis / 1000.0, 0.0)
    except Exception:
        return 0.0


def _foreground_info(record_title: bool):
    """取前台窗口 (app, title)；无前台/自身进程/忽略进程返回 None。"""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid = pid.value
        if not pid or pid == os.getpid():
            return None
        if not PSUTIL_AVAILABLE:
            return None
        try:
            proc = psutil.Process(pid)
            app = proc.name()
        except Exception:
            return None
        if not app or app.lower() in IGNORED_APPS:
            return None
        title = ""
        if record_title:
            try:
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()[:200]
            except Exception:
                title = ""
        return app, title
    except Exception:
        return None


class AppObserver:
    """前台应用观察器：轮询前台窗口，按会话统计各应用使用时长。"""

    def __init__(self, data_dir: str, poll_seconds: float = 1.0,
                 idle_threshold_seconds: int = 300, record_title: bool = True,
                 aliases: dict = None):
        self._data_dir = Path(data_dir)
        self._db_path = self._data_dir / "app_usage.db"
        self._state_path = self._data_dir / "app_state.json"
        self._poll = max(float(poll_seconds), 0.5)
        self._idle_threshold = max(int(idle_threshold_seconds), 30)
        self._record_title = record_title
        self._aliases = {str(k).lower(): str(v) for k, v in (aliases or {}).items()}

        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._db = None
        self._on_switch = None
        self._last_state_write = 0.0

        # 当前会话状态
        self._cur_app = None
        self._cur_title = ""
        self._cur_start = None
        self._idle = False

    # ---------- 生命周期 ----------
    def start(self):
        if not IS_WIN:
            logger.info("非 Windows 平台，应用统计不可用")
            return
        if not PSUTIL_AVAILABLE:
            logger.warning("psutil 未安装，应用统计不可用（pip install psutil）")
            return
        if self._running:
            return
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.commit()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="AppObserver")
        self._thread.start()
        logger.info("应用使用统计已启动（间隔 %.1fs，离开阈值 %ds）", self._poll, self._idle_threshold)

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        with self._lock:
            self._end_session_locked(datetime.now())
            if self._db is not None:
                try:
                    self._db.commit()
                    self._db.close()
                except Exception:
                    pass
                self._db = None
        logger.info("应用使用统计已停止")

    def set_on_switch(self, callback):
        """注册应用切换回调：cb({"app","title","start"})，在 observer 线程中调用。"""
        self._on_switch = callback

    # ---------- 轮询 ----------
    def _loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.debug("应用统计轮询异常: %s", e)
            time.sleep(self._poll)

    def _tick(self):
        now = datetime.now()
        idle_for = _idle_seconds()

        if idle_for >= self._idle_threshold:
            # 进入/处于离开状态：结束会话（结束时间回推到输入停止时刻）
            with self._lock:
                if not self._idle:
                    self._idle = True
                    away_since = now - timedelta(seconds=idle_for)
                    self._end_session_locked(away_since)
                    self._write_state_locked(now)
            return

        info = _foreground_info(self._record_title)
        if info is None:
            return
        app, title = info

        with self._lock:
            was_idle = self._idle
            self._idle = False
            if app != self._cur_app:
                self._end_session_locked(now)
                self._cur_app = app
                self._cur_title = title
                self._cur_start = now
                self._learn_alias_locked(app, title)
                self._write_state_locked(now)
                switch_info = {"app": app, "title": title, "start": now.isoformat()}
            else:
                switch_info = None
                if title and title != self._cur_title:
                    self._cur_title = title
                    self._learn_alias_locked(app, title)
                # 无切换时节流写状态文件（面板心跳读取）
                if was_idle or (time.time() - self._last_state_write) > 5:
                    self._write_state_locked(now)

        if switch_info is not None and self._on_switch is not None:
            try:
                self._on_switch(switch_info)
            except Exception as e:
                logger.debug("应用切换回调异常: %s", e)

    def _end_session_locked(self, end_time: datetime):
        """结束当前会话并落库（须持有 _lock）。"""
        if self._cur_app is None or self._cur_start is None or self._db is None:
            self._cur_app = None
            self._cur_start = None
            return
        duration = (end_time - self._cur_start).total_seconds()
        app, title, start = self._cur_app, self._cur_title, self._cur_start
        self._cur_app = None
        self._cur_start = None
        if duration < 1:
            return  # 不足 1 秒的切换抖动不计
        try:
            self._db.execute(
                "INSERT INTO sessions(date, app, title, start, duration) VALUES(?,?,?,?,?)",
                (start.strftime("%Y-%m-%d"), app, title,
                 start.strftime("%Y-%m-%d %H:%M:%S"), duration),
            )
            self._db.commit()
        except Exception as e:
            logger.debug("会话写入失败: %s", e)

    # ---------- 别名 / 类别学习 ----------
    def resolve_alias(self, app: str, title: str = "") -> str:
        key = app.lower()
        if key in self._aliases:
            return self._aliases[key]
        if key in KNOWN_ALIASES:
            return KNOWN_ALIASES[key]
        learned = self._meta_get(key).get("alias")
        if learned:
            return learned
        if title and " - " in title:
            cand = title.rsplit(" - ", 1)[-1].strip()
            if 2 <= len(cand) <= 12:
                return cand
        stem = app.rsplit(".", 1)[0] if "." in app else app
        return stem

    def _learn_alias_locked(self, app: str, title: str):
        """从窗口标题学习别名（仅当该应用还没有别名时）。"""
        key = app.lower()
        if key in self._aliases or key in KNOWN_ALIASES or not title or " - " not in title:
            return
        cand = title.rsplit(" - ", 1)[-1].strip()
        if not (2 <= len(cand) <= 12):
            return
        if self._meta_get(key).get("alias"):
            return
        self._meta_upsert_locked(key, alias=cand)

    def update_app_category(self, app: str, category: str):
        """根据 AI 卡片类别累计投票，多数决写入 app_meta.category。"""
        if not app or not category or self._db is None:
            return
        key = app.lower()
        with self._lock:
            meta = self._meta_get(key)
            counts = meta.get("cat_counts") or {}
            counts[category] = counts.get(category, 0) + 1
            top = max(counts.items(), key=lambda kv: kv[1])[0]
            self._meta_upsert_locked(key, category=top, cat_counts=counts)

    def _meta_get(self, app_key: str) -> dict:
        if self._db is None:
            return {}
        try:
            row = self._db.execute(
                "SELECT alias, category, cat_counts FROM app_meta WHERE app=?", (app_key,)
            ).fetchone()
            if not row:
                return {}
            try:
                counts = json.loads(row[2] or "{}")
            except Exception:
                counts = {}
            return {"alias": row[0], "category": row[1], "cat_counts": counts}
        except Exception:
            return {}

    def _meta_upsert_locked(self, app_key: str, alias=None, category=None, cat_counts=None):
        if self._db is None:
            return
        try:
            cur = self._meta_get(app_key)
            self._db.execute(
                "INSERT OR REPLACE INTO app_meta(app, alias, category, cat_counts, updated)"
                " VALUES(?,?,?,?,?)",
                (
                    app_key,
                    alias if alias is not None else cur.get("alias"),
                    category if category is not None else cur.get("category"),
                    json.dumps(cat_counts if cat_counts is not None else (cur.get("cat_counts") or {}),
                               ensure_ascii=False),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            self._db.commit()
        except Exception as e:
            logger.debug("app_meta 写入失败: %s", e)

    # ---------- 状态输出 ----------
    def get_current(self):
        """当前会话快照：{app, title, start, duration, is_idle, alias}；无则 None。"""
        with self._lock:
            if self._cur_app is None or self._cur_start is None:
                return {"is_idle": self._idle} if self._idle else None
            return {
                "app": self._cur_app,
                "title": self._cur_title,
                "start": self._cur_start.isoformat(),
                "duration": (datetime.now() - self._cur_start).total_seconds(),
                "is_idle": self._idle,
                "alias": self.resolve_alias(self._cur_app, self._cur_title),
            }

    def _write_state_locked(self, now: datetime):
        """把当前会话状态写 app_state.json（面板读取用）。"""
        try:
            if self._cur_app is not None and self._cur_start is not None:
                state = {
                    "app": self._cur_app,
                    "title": self._cur_title,
                    "start": self._cur_start.isoformat(),
                    "is_idle": self._idle,
                    "alias": self.resolve_alias(self._cur_app, self._cur_title),
                    "updated_at": now.isoformat(),
                }
            else:
                state = {"app": None, "is_idle": self._idle, "updated_at": now.isoformat()}
            self._state_path.write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )
            self._last_state_write = time.time()
        except Exception as e:
            logger.debug("状态文件写入失败: %s", e)


# ---------- 只读查询（面板 / 统计用，独立连接） ----------
def load_app_totals(db_path, date_from: str = None, date_to: str = None) -> dict:
    """按应用汇总时长（秒）。date_from/date_to 为 'YYYY-MM-DD'（含端点）。"""
    p = Path(db_path)
    if not p.exists():
        return {}
    try:
        db = sqlite3.connect(str(p))
        try:
            sql = "SELECT LOWER(app), SUM(duration) FROM sessions"
            cond, params = [], []
            if date_from:
                cond.append("date >= ?")
                params.append(date_from)
            if date_to:
                cond.append("date <= ?")
                params.append(date_to)
            if cond:
                sql += " WHERE " + " AND ".join(cond)
            sql += " GROUP BY LOWER(app)"
            return {row[0]: float(row[1]) for row in db.execute(sql, params)}
        finally:
            db.close()
    except Exception as e:
        logger.debug("读取应用时长失败: %s", e)
        return {}


def load_app_meta(db_path) -> dict:
    """读取 app_meta：{app_key: {alias, category}}。"""
    p = Path(db_path)
    if not p.exists():
        return {}
    try:
        db = sqlite3.connect(str(p))
        try:
            out = {}
            for app, alias, category in db.execute("SELECT app, alias, category FROM app_meta"):
                out[app] = {"alias": alias, "category": category}
            return out
        except sqlite3.Error:
            return {}
        finally:
            db.close()
    except Exception as e:
        logger.debug("读取 app_meta 失败: %s", e)
        return {}


def load_app_state(data_dir) -> dict:
    """读取 app_state.json（observer 写的当前会话状态），失败返回 {}。"""
    p = Path(data_dir) / "app_state.json"
    if not p.exists():
        return {}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}
