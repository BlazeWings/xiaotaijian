"""系统最顶层悬浮面板（PySide6 / Qt）

功能：
- 默认置顶显示（系统最顶层），可切换
- 计时器（Catime 式多模态）：番茄钟 / 倒计时 / 秒表
  - 番茄钟：专注/短休息/长休息自动轮换，支持自定义阶段序列（config pomodoro.times）
  - 倒计时：点击时间数字自定义时长（支持 "25"=25分钟、"90s"、"1h 30m"、"130 20"），
    到 0 响铃后自动转正计时（+ 前缀继续累计），可配到点打开网站
  - 秒表：正计时
- 当前任务：手动记录“现在在干什么”，大字提醒（点击可改，持久化到 ui_state.json）
- 当前事件 + 最近事件历史（实时读取 data/cards.json）
- 时间排名：相似事件自动归类，按累计时长排名（今日/本周/全部）
- 最小化视图：只显示计时器 + 当前任务 + 当前事件

启动：python main.py ui
"""
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPropertyAnimation, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import activity_stats as stats
from . import forced_mode as fm

logger = logging.getLogger(__name__)

# 强制模式黑名单文件路径（exe 运行时 cwd 已被 main.py 切换到 exe 目录）
FORBIDDEN_FILE = str(Path.cwd() / "forbidden.txt")

# Win32 SetWindowPos：用于周期性重新声明置顶（防止被其他置顶窗口/无边框游戏抢走顶层）
_SWP = None
if sys.platform == "win32":
    try:
        import ctypes
        _SWP = ctypes.windll.user32.SetWindowPos
        _SWP.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint,
        ]
        _SWP.restype = ctypes.c_int
    except Exception:
        _SWP = None
_HWND_TOPMOST = -1
_SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE

# ---------- 主题（新粗野主义 Neobrutalism：米色底 + 黑粗描边 + 硬阴影 + 平涂亮色） ----------
BG = "#f5f0e6"          # 米色背景
PANEL = "#ffffff"       # 纯白卡片
BORDER = "#000000"      # 黑色粗描边
TEXT = "#111111"
MUTED = "#5c5c5c"
ACCENT = "#ff6b6b"      # 主色红
ACCENT_HOVER = "#ff8787"
ACCENT_DARK = "#e03131"
GREEN = "#2f9e44"
YELLOW = "#ffd43b"      # 高亮黄（hover / 选中态）
YELLOW_HOVER = "#ffe066"

CATEGORY_COLORS = {
    "工作/学习": "#4dabf7",
    "娱乐休闲": "#ffa94d",
    "通讯交流": "#51cf66",
    "信息检索": "#ffd43b",
    "系统操作": "#9775fa",
    "其他": "#adb5bd",
}

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei UI";
    font-size: 12px;
}}
QLabel {{ background: transparent; }}
QFrame#panel {{
    background: {PANEL};
    border: 2px solid {BORDER};
    border-right-width: 5px;
    border-bottom-width: 5px;
    border-radius: 0px;
}}
QLabel#sectionTitle {{ font-size: 12px; font-weight: 800; color: {TEXT}; }}
QLabel#pomoTime {{ font-size: 36px; font-weight: 800; color: {ACCENT}; }}
QLabel#phaseLabel {{ font-size: 12px; font-weight: 800; color: {ACCENT}; }}
QLabel#curDesc {{ font-size: 13px; font-weight: 700; }}
QLabel#curMeta {{ font-size: 11px; color: {MUTED}; }}
QLabel#foot {{ font-size: 10px; color: {MUTED}; }}
QPushButton {{
    background: {PANEL};
    color: {TEXT};
    border: 2px solid {BORDER};
    border-radius: 0px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 700;
}}
QPushButton:hover {{ background: {YELLOW}; }}
QPushButton:pressed {{ background: {YELLOW_HOVER}; }}
QPushButton#accent {{ background: {ACCENT}; color: #ffffff; font-weight: 800; }}
QPushButton#accent:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#accent:pressed {{ background: {ACCENT_DARK}; }}
QPushButton#ghost {{
    background: transparent;
    color: {MUTED};
    border: 2px solid transparent;
    padding: 4px 8px;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#ghost:hover {{ background: {YELLOW}; border: 2px solid {BORDER}; color: {TEXT}; }}
QPushButton#ghostActive {{
    background: {YELLOW};
    color: {TEXT};
    border: 2px solid {BORDER};
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 800;
}}
QPushButton#ghostActive:hover {{ background: {YELLOW_HOVER}; }}
QPushButton#chip {{
    background: #e9ecef;
    color: {TEXT};
    border: 2px solid {BORDER};
    border-radius: 0px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 700;
}}
QProgressBar {{
    background: {PANEL};
    border: 2px solid {BORDER};
    border-radius: 0px;
    height: 12px;
}}
QProgressBar::chunk {{ background: {ACCENT}; }}
QProgressBar#rankbar {{ height: 8px; }}
QProgressBar#rankbar::chunk {{ background: #4dabf7; }}
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{ padding: 3px 2px; border-radius: 0px; }}
QListWidget::item:hover {{ background: {YELLOW_HOVER}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{
    background: {PANEL};
    color: {TEXT};
    border: 2px solid {BORDER};
    padding: 4px 6px;
}}
"""

PHASE_NAMES = {
    "work": "🍅 专注中",
    "break": "☕ 短休息",
    "long_break": "🌴 长休息",
}

MODE_NAMES = {
    "pomodoro": "🍅 番茄钟",
    "countdown": "⏳ 倒计时",
    "stopwatch": "⏱ 秒表",
}


def _cat_color(cat: str) -> str:
    return CATEGORY_COLORS.get(str(cat), CATEGORY_COLORS["其他"])


def _elide(text: str, width: int, font: QFont = None) -> str:
    fm = QFontMetrics(font or QFont())
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, width)


def _parse_duration_text(text: str):
    """Catime 式时长解析，返回秒数；非法输入返回 None。

    支持：
    - 带单位："25m"、"90s"、"1h 30m"、"2h3m"
    - 简写数字："25"（分钟）、"130 20"（130分20秒）、"1 30 15"（1时30分15秒）
    """
    t = (text or "").strip().lower()
    if not t:
        return None

    # 带单位：h / m / s
    if re.search(r"[hms]", t):
        total = 0
        found = False
        for match in re.finditer(r"(\d+)\s*([hms])", t):
            value = int(match.group(1))
            unit = match.group(2)
            if unit == "h":
                total += value * 3600
            elif unit == "m":
                total += value * 60
            else:
                total += value
            found = True
        return total if found and total > 0 else None

    # 纯数字简写：1 个=分钟，2 个=分 秒，3 个=时 分 秒
    parts = [p for p in t.split() if p]
    if parts and all(p.isdigit() for p in parts):
        nums = [int(p) for p in parts]
        if len(nums) == 1:
            return nums[0] * 60
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def _fmt_time(seconds: int) -> str:
    """自适应格式化：M:SS / H:MM:SS（Catime 式按量级切换）。"""
    seconds = max(int(seconds), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------- 数据刷新工作线程 ----------
class DataWorker(QObject):
    """在后台线程读取 cards.json 并构建视图数据，避免阻塞 UI。"""

    finished_ok = Signal(object)

    def __init__(self, data_dir: str, config: dict):
        super().__init__()
        self._data_dir = data_dir
        self._scope = str(config.get("ui", {}).get("rank_scope", "today"))
        self._top = int(config.get("ui", {}).get("rank_top", 8))
        self._cap = int(config.get("ui", {}).get("rank_cap_minutes", 15)) * 60
        self._history_max = int(config.get("ui", {}).get("history_max", 30))
        # "全部"排名统计上限：0（默认）= 不限制，统计全部历史记录
        self._rank_max_cards = int(config.get("ui", {}).get("rank_max_cards", 0))
        # 应用别名配置（app_tracker.aliases）
        self._aliases = dict(config.get("app_tracker", {}).get("aliases") or {})

    @Slot()
    def reload(self):
        try:
            view = stats.build_view(
                self._data_dir,
                scope=self._scope,
                top=self._top,
                cap_seconds=self._cap,
                history_max=self._history_max,
                max_cards=self._rank_max_cards,
                aliases=self._aliases,
            )
            self.finished_ok.emit(view)
        except Exception as e:
            logger.warning("刷新面板数据失败: %s", e)

    @Slot(str)
    def set_scope(self, scope: str):
        self._scope = scope
        self.reload()


# ---------- 排名行 ----------
class RankRow(QFrame):
    def __init__(self, item: dict, font: QFont, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(f"QFrame#panel {{ background: {PANEL}; border: 2px solid {BORDER}; border-radius: 0px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)

        is_current = bool(item.get("is_current"))
        top = QHBoxLayout()
        top.setSpacing(8)
        rank_label = QLabel("▶" if is_current else f"#{item['rank']}")
        if is_current:
            rank_label.setStyleSheet(f"font-weight:700; color:{GREEN}; font-size:12px;")
        else:
            rank_label.setStyleSheet(f"font-weight:700; color:{ACCENT}; font-size:12px;")
        desc_label = QLabel(_elide(item["label"], 245, font))
        desc_label.setStyleSheet("font-size:12px;")
        desc_label.setMaximumWidth(250)
        desc_label.setToolTip(item["label"])
        time_label = QLabel(stats.format_duration(item["total"]))
        time_label.setStyleSheet(f"font-size:11px; color:{MUTED};")
        if is_current:
            time_label.setToolTip("当前进行中的事件（实时累计）")
        top.addWidget(rank_label)
        top.addWidget(desc_label, 1)
        top.addWidget(time_label)
        lay.addLayout(top)

        bar = QProgressBar()
        bar.setObjectName("rankbar")
        bar.setRange(0, 100)
        bar.setValue(int(item["share"] * 100))
        bar.setTextVisible(False)
        lay.addWidget(bar)

        self._time_label = time_label
        self._bar = bar

    def update_item(self, item: dict):
        """心跳实时更新时长与进度（不重建行）。"""
        self._time_label.setText(stats.format_duration(item["total"]))
        self._bar.setValue(int(max(item.get("share", 0.0), 0.0) * 100))


# ---------- 历史事件行 ----------
class HistoryRow(QFrame):
    def __init__(self, card: dict, font: QFont, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: transparent; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(8)

        cat = str(card.get("category") or "其他")
        color = _cat_color(cat)
        desc = str(card.get("description") or "未知活动")
        # 应用别名前缀（AppObserver 数据）：微信 · 正在群聊…
        app_alias = str(card.get("app_alias") or "").strip()
        if app_alias:
            desc = f"{app_alias} · {desc}"

        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:10px;")
        time_label = QLabel(stats.format_hhmm(card))
        time_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        desc_label = QLabel(_elide(desc, 225, font))
        desc_label.setToolTip(desc)
        desc_label.setStyleSheet("font-size:12px;")
        cat_label = QLabel(f"[{cat}]")
        cat_label.setStyleSheet(f"color:{color}; font-size:11px;")

        lay.addWidget(dot)
        lay.addWidget(time_label)
        lay.addWidget(desc_label, 1)
        lay.addWidget(cat_label)


# ---------- 悬浮面板主窗口 ----------
class OverlayWindow(QWidget):
    _reload_request = Signal(str)
    _force_blocked = Signal(str)

    def __init__(self, config: dict, data_dir: str = "data", app=None):
        super().__init__()

        self._config = config
        self._data_dir = str(data_dir)
        self._app = app
        self._view = None
        self._mini = False
        self._topmost = True
        self._fade_mode = False
        self._fade_opacity = 0.30
        self._fade_anim = None
        self._scope = str(config.get("ui", {}).get("rank_scope", "today"))
        self._last_mtime = None
        self._last_size = None
        self._last_app_key = None  # app_state.json 中 (app, is_idle)，用于检测应用切换

        # 计时器配置（Catime 式多模态：番茄钟/倒计时/秒表）
        pomo = config.get("pomodoro", {}) or {}
        self._work_sec = int(pomo.get("work_minutes", 25)) * 60
        self._break_sec = int(pomo.get("break_minutes", 5)) * 60
        self._long_break_sec = int(pomo.get("long_break_minutes", 15)) * 60
        self._rounds_target = int(pomo.get("rounds", 4))
        # 自定义番茄阶段序列（分钟列表，如 [25,5,25,15]；未配置则用 work/break/long_break 传统逻辑）
        self._pomo_times = []
        raw_times = pomo.get("times")
        if isinstance(raw_times, list) and raw_times:
            self._pomo_times = [max(int(x), 1) * 60 for x in raw_times if str(x).strip().lstrip("-").isdigit() and int(x) > 0]
        self._mode = "pomodoro"          # pomodoro | countdown | stopwatch
        self._direction = "down"         # down 倒计时 | up 正计时
        self._phase = "work"
        self._phase_index = 0            # 番茄序列阶段索引
        self._countdown_sec = self._work_sec  # 倒计时模式默认时长
        self._remaining = self._work_sec
        self._rounds_done = 0
        self._running = False
        self._overflow = False           # 倒计时到 0 后转正计时标记
        self._base_mono = 0.0            # 防漂移：计时基准（time.monotonic）
        self._base_value = 0             # 基准时点的剩余/已过秒数

        # 到时超时动作：打开网站（config 默认 + data/ui_state.json 用户覆盖）
        self._timeout_website = str(pomo.get("timeout_website", "") or "").strip()
        self._task_text = ""
        self._ui_state_path = Path(self._data_dir) / "ui_state.json"
        try:
            if self._ui_state_path.exists():
                import json as _json
                state = _json.loads(self._ui_state_path.read_text(encoding="utf-8"))
                if isinstance(state, dict):
                    if state.get("timeout_website") is not None:
                        self._timeout_website = str(state["timeout_website"]).strip()
                    if state.get("current_task") is not None:
                        self._task_text = str(state["current_task"]).strip()
        except Exception:
            pass

        # 排名时长封顶（秒），心跳实时更新用
        self._cap_seconds = int(config.get("ui", {}).get("rank_cap_minutes", 15)) * 60
        self._rank_rows = []

        # 强制模式：黑名单文件 + 监控实例 + 折叠状态
        self._forbidden_file = FORBIDDEN_FILE
        self._forced_monitor = None
        self._self_owned_monitor = False
        # 关闭强制模式后，定时自动重新开启（monotonic 秒时间戳，None = 未安排）
        self._force_reopen_at_mono = None
        self._force_reopen_total = 0

        self.setWindowTitle("番茄钟悬浮面板")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(QSS)

        self._font = QFont("Microsoft YaHei UI", 10)
        self.setFont(self._font)

        self._build_ui()
        self._build_pomodoro()

        # 数据线程
        self._thread = QThread(self)
        self._worker = DataWorker(self._data_dir, config)
        self._worker.moveToThread(self._thread)
        self._thread.start()
        self._reload_request.connect(self._worker.set_scope)
        self._worker.finished_ok.connect(self._apply_view)

        # 定时检查数据文件变化
        refresh = max(int(config.get("ui", {}).get("refresh_seconds", 3)), 1)
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_data_file)
        self._watch.start(refresh * 1000)

        self._check_data_file()

        # 窗口位置：屏幕右上角
        screen = QApplication.primaryScreen().availableGeometry()
        self._apply_size()
        self.move(screen.right() - self.width() - 16, screen.top() + 16)

        self._pomo_tick = QTimer(self)
        self._pomo_tick.setInterval(1000)
        self._pomo_tick.timeout.connect(self._on_pomo_tick)

        # 结合模式：定时轮询同进程监控状态
        if self._app is not None:
            self._mon_timer = QTimer(self)
            self._mon_timer.setInterval(2000)
            self._mon_timer.timeout.connect(self._poll_monitor_status)
            self._mon_timer.start()
            self._poll_monitor_status()

        # 实时心跳：每秒滚动更新“当前事件已持续”与排名中当前分组的累计时长
        self._live_tick = QTimer(self)
        self._live_tick.setInterval(1000)
        self._live_tick.timeout.connect(self._tick_live)
        self._live_tick.start()

        # 强制模式状态轮询（运行状态可能被 app 启动/停止，周期同步到 UI）
        self._force_timer = QTimer(self)
        self._force_timer.setInterval(1000)
        self._force_timer.timeout.connect(self._poll_force_status)
        self._force_timer.start()

        # 关闭强制模式后到点自动重新开启
        self._force_reopen_timer = QTimer(self)
        self._force_reopen_timer.setSingleShot(True)
        self._force_reopen_timer.timeout.connect(self._reopen_force_mode)

        # 周期性重新声明置顶：其他置顶窗口/无边框游戏出现后会盖住面板，定时抢回顶层
        self._top_timer = QTimer(self)
        self._top_timer.setInterval(1000)
        self._top_timer.timeout.connect(self._reassert_topmost)
        self._top_timer.start()

    # ---------- 尺寸 ----------
    _FULL_W = 480
    _FULL_H = 860
    _MINI_W = 320
    _MINI_H = 400

    def _apply_size(self):
        """按当前模式锁定窗口尺寸（完整模式高度自适应屏幕；强制模式展开时加高）。"""
        if self._mini:
            self.setFixedSize(self._MINI_W, self._MINI_H)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            extra = 260 if getattr(self, "_force_expanded", False) else 0
            h = min(self._FULL_H + extra, max(460, screen.height() - 40))
            self.setFixedSize(self._FULL_W, h)

    # ---------- 构建 UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 顶部标题栏（可拖动）
        header = QFrame(self)
        header.setObjectName("panel")
        header.setCursor(Qt.CursorShape.OpenHandCursor)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(12, 8, 8, 8)
        hlay.setSpacing(4)
        self._title_label = QLabel("🍅 番茄钟悬浮面板")
        self._title_label.setStyleSheet("font-size:14px; font-weight:800;")
        hlay.addWidget(self._title_label)

        # 监控状态（start --ui 结合模式时显示）
        self._mon_dot = QLabel("●")
        self._mon_dot.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self._mon_txt = QLabel("")
        self._mon_txt.setStyleSheet(f"font-size:11px; color:{MUTED};")
        hlay.addWidget(self._mon_dot)
        hlay.addWidget(self._mon_txt)
        if self._app is None:
            self._mon_dot.hide()
            self._mon_txt.hide()

        hlay.addStretch(1)

        self._pin_btn = self._ghost_btn("📌", self._toggle_topmost, tooltip="切换置顶")
        self._fade_btn = self._ghost_btn("👻", self._toggle_fade, tooltip="淡化模式：窗口半透明，可看到后面的内容")
        self._mini_btn = self._ghost_btn("─", self._toggle_mini, tooltip="最小化（只显示计时器、当前任务和当前事件）")
        self._close_btn = self._ghost_btn("✕", self.close, tooltip="退出面板")
        hlay.addWidget(self._pin_btn)
        hlay.addWidget(self._fade_btn)
        hlay.addWidget(self._mini_btn)
        hlay.addWidget(self._close_btn)
        root.addWidget(header)

        # 番茄钟卡片
        self._pomo_card = self._panel()
        p = QVBoxLayout(self._pomo_card)
        p.setContentsMargins(14, 10, 14, 10)
        p.setSpacing(5)
        p_row1 = QHBoxLayout()
        p_row1.setSpacing(4)
        # 模式切换：番茄钟 / 倒计时 / 秒表
        self._mode_btn_pomodoro = self._ghost_btn("🍅", lambda: self._set_mode("pomodoro"), tooltip="番茄钟")
        self._mode_btn_countdown = self._ghost_btn("⏳", lambda: self._set_mode("countdown"), tooltip="倒计时（点击时间数字可自定义时长）")
        self._mode_btn_stopwatch = self._ghost_btn("⏱", lambda: self._set_mode("stopwatch"), tooltip="秒表")
        self._phase_label = QLabel(PHASE_NAMES["work"])
        self._phase_label.setObjectName("phaseLabel")
        self._round_label = QLabel("")
        self._round_label.setStyleSheet(f"font-size:11px; color:{MUTED};")
        self._link_btn = self._ghost_btn("🔗", self._set_timeout_website,
                                         tooltip="到时自动打开网站（点击设置网址）")
        self._link_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {MUTED}; border: 2px solid transparent; padding: 2px 8px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {YELLOW}; border: 2px solid {BORDER}; color: {TEXT}; }}"
        )
        p_row1.addWidget(self._mode_btn_pomodoro)
        p_row1.addWidget(self._mode_btn_countdown)
        p_row1.addWidget(self._mode_btn_stopwatch)
        p_row1.addWidget(self._phase_label)
        p_row1.addStretch(1)
        p_row1.addWidget(self._round_label)
        p_row1.addWidget(self._link_btn)
        p.addLayout(p_row1)

        self._pomo_time = QLabel("25:00")
        self._pomo_time.setObjectName("pomoTime")
        self._pomo_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pomo_time.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pomo_time.mousePressEvent = self._on_time_click
        p.addWidget(self._pomo_time)

        self._pomo_bar = QProgressBar()
        self._pomo_bar.setRange(0, self._work_sec)
        self._pomo_bar.setValue(0)
        self._pomo_bar.setTextVisible(False)
        p.addWidget(self._pomo_bar)

        p_btns = QHBoxLayout()
        p_btns.setSpacing(8)
        self._start_btn = QPushButton("▶ 开始")
        self._start_btn.setObjectName("accent")
        self._start_btn.clicked.connect(self._toggle_running)
        self._reset_btn = QPushButton("重置")
        self._reset_btn.clicked.connect(self._reset_pomo)
        self._skip_btn = QPushButton("跳过")
        self._skip_btn.clicked.connect(self._skip_pomo)
        p_btns.addWidget(self._start_btn, 1)
        p_btns.addWidget(self._reset_btn, 1)
        p_btns.addWidget(self._skip_btn, 1)
        p.addLayout(p_btns)
        root.addWidget(self._pomo_card)

        # 🎯 当前任务卡片（手动输入提醒，完整与最小化都显示）
        self._build_task_card(root)

        # 当前事件卡片
        self._cur_card = self._panel()
        c = QVBoxLayout(self._cur_card)
        c.setContentsMargins(14, 8, 14, 8)
        c.setSpacing(4)
        c_row = QHBoxLayout()
        cur_title = QLabel("📌 当前事件")
        cur_title.setObjectName("sectionTitle")
        self._cur_chip = QPushButton("其他")
        self._cur_chip.setObjectName("chip")
        self._cur_chip.setEnabled(False)
        c_row.addWidget(cur_title)
        c_row.addStretch(1)
        c_row.addWidget(self._cur_chip)
        c.addLayout(c_row)
        # 应用行（AppObserver 数据）：显示当前前台应用别名 / 离开状态
        self._cur_app = QLabel("")
        self._cur_app.setStyleSheet(f"font-size:14px; font-weight:800; color:{TEXT};")
        self._cur_app.hide()
        c.addWidget(self._cur_app)
        self._cur_desc = QLabel("暂无记录")
        self._cur_desc.setObjectName("curDesc")
        self._cur_desc.setWordWrap(True)
        self._cur_desc.setMinimumHeight(30)
        self._cur_meta = QLabel("等待监控产生记录…")
        self._cur_meta.setObjectName("curMeta")
        c.addWidget(self._cur_desc)
        c.addWidget(self._cur_meta)
        root.addWidget(self._cur_card)

        # 强制模式卡片（可折叠）
        self._build_force_card(root)

        # 最近事件卡片
        self._hist_card = self._panel()
        h = QVBoxLayout(self._hist_card)
        h.setContentsMargins(12, 10, 12, 8)
        h.setSpacing(6)
        h_title = QLabel("🕘 最近事件")
        h_title.setObjectName("sectionTitle")
        h.addWidget(h_title)
        self._hist_list = QListWidget()
        self._hist_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._hist_list.setFixedHeight(100)
        h.addWidget(self._hist_list)
        root.addWidget(self._hist_card)

        # 时间排名卡片（吸收剩余空间，允许垂直压缩）
        self._rank_card = self._panel()
        self._rank_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        r = QVBoxLayout(self._rank_card)
        r.setContentsMargins(12, 10, 12, 10)
        r.setSpacing(6)
        r_title_row = QHBoxLayout()
        r_title = QLabel("🏆 时间排名")
        r_title.setObjectName("sectionTitle")
        self._scope_today = self._ghost_btn("今日", lambda: self._set_scope("today"))
        self._scope_week = self._ghost_btn("本周", lambda: self._set_scope("week"))
        self._scope_all = self._ghost_btn("全部", lambda: self._set_scope("all"))
        r_title_row.addWidget(r_title)
        r_title_row.addStretch(1)
        r_title_row.addWidget(self._scope_today)
        r_title_row.addWidget(self._scope_week)
        r_title_row.addWidget(self._scope_all)
        r.addLayout(r_title_row)
        self._rank_scroll = QScrollArea()
        self._rank_scroll.setWidgetResizable(True)
        self._rank_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rank_scroll.setMaximumHeight(300)
        self._rank_scroll.setMinimumHeight(110)
        rank_inner = QWidget()
        rank_inner.setObjectName("rankInner")
        # 注意：必须带选择器，无选择器的样式会作用于所有后代并覆盖按钮配色
        rank_inner.setStyleSheet("QWidget#rankInner { background: transparent; }")
        self._rank_box = QVBoxLayout(rank_inner)
        self._rank_box.setContentsMargins(0, 0, 4, 0)
        self._rank_box.setSpacing(5)
        self._rank_empty = QLabel("暂无排名数据")
        self._rank_empty.setStyleSheet(f"color:{MUTED}; padding:6px 0;")
        self._rank_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rank_box.addWidget(self._rank_empty)
        self._rank_scroll.setWidget(rank_inner)
        r.addWidget(self._rank_scroll)
        # 排名卡片吸收布局剩余空间（其他卡片保持内容高度）
        root.addWidget(self._rank_card, 1)

        # 页脚：数据状态 + 一键打开卡片文件夹
        foot_row = QHBoxLayout()
        foot_row.setSpacing(6)
        self._footer = QLabel("")
        self._footer.setObjectName("foot")
        self._cards_btn = self._ghost_btn("📂 卡片", self._open_cards_folder,
                                          tooltip="打开卡片文件夹（data/cards）")
        self._cards_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {MUTED}; border: 2px solid transparent; padding: 2px 8px; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {YELLOW}; border: 2px solid {BORDER}; color: {TEXT}; }}"
        )
        foot_row.addWidget(self._footer, 1)
        foot_row.addWidget(self._cards_btn)
        root.addLayout(foot_row)

        # 标题栏拖拽 / 双击切换最小化
        header.mousePressEvent = self._on_header_press
        header.mouseMoveEvent = self._on_header_move
        header.mouseDoubleClickEvent = lambda e: self._toggle_mini()

    # ---------- 🎯 当前任务卡片 ----------
    def _build_task_card(self, root):
        """手动输入“我现在在干什么”的任务提醒栏，完整 & 最小化都显示。"""
        card = self._panel()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(3)

        row = QHBoxLayout()
        row.setSpacing(6)
        title = QLabel("🎯 当前任务")
        title.setObjectName("sectionTitle")
        self._task_status = QLabel("")
        self._task_status.setStyleSheet(f"font-size:11px; color:{MUTED};")
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self._task_status)
        lay.addLayout(row)

        # 任务内容（点击可编辑）
        self._task_text_label = QLabel("")
        self._task_text_label.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{ACCENT};"
        )
        self._task_text_label.setWordWrap(True)
        self._task_text_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._task_text_label.mousePressEvent = self._on_task_click
        lay.addWidget(self._task_text_label)

        root.addWidget(card)
        self._task_card = card
        self._update_task_label()

    def _on_task_click(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_current_task()

    def _set_current_task(self):
        """弹出输入框让用户填写当前任务（留空 = 清除提醒）。"""
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self,
            "记录当前任务",
            "现在在干什么 / 当前需要专注的任务：\n（留空并确定 = 清除，填写后随时可修改）",
            text=self._task_text,
        )
        if not ok:
            return
        self._task_text = text.strip()
        self._save_ui_state()
        self._update_task_label()

    def _update_task_label(self):
        if self._task_text:
            self._task_label_full = self._task_text
            self._task_text_label.setText(self._task_text)
            self._task_text_label.setStyleSheet(
                f"font-size:14px; font-weight:700; color:{ACCENT};"
            )
            self._task_text_label.setToolTip("点击修改当前任务：另存提醒")
            self._task_status.setText("· 进行中")
        else:
            self._task_text_label.setText("点击设置当前任务")
            self._task_text_label.setStyleSheet(
                f"font-size:13px; font-weight:600; color:{MUTED};"
            )
            self._task_text_label.setToolTip("点击设置当前任务")
            self._task_status.setText("")

    # ---------- 强制模式卡片 ----------
    def _build_force_card(self, root):
        """⛔ 强制模式卡片：状态开关 + 黑名单管理（可折叠）。"""
        card = self._panel()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(5)

        # 标题行
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel("⛔ 强制模式")
        title.setObjectName("sectionTitle")
        self._force_status = QLabel("")
        self._force_status.setStyleSheet(f"font-size:11px; font-weight:600; color:{MUTED};")
        self._force_toggle_btn = QPushButton("○ 开启")
        self._force_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._force_toggle_btn.clicked.connect(self._toggle_force_mode)
        self._force_expand_btn = self._ghost_btn("▸", self._toggle_force_expand,
                                                 tooltip="展开黑名单管理")
        self._force_expand_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {MUTED}; padding: 2px 6px; font-size: 13px; }}"
        )
        title_row.addWidget(title)
        title_row.addWidget(self._force_status)
        title_row.addStretch(1)
        title_row.addWidget(self._force_toggle_btn)
        title_row.addWidget(self._force_expand_btn)
        lay.addLayout(title_row)

        # 折叠区：黑名单列表 + 添加按钮
        self._force_body = QWidget()
        self._force_body.setObjectName("forceBody")
        # 注意：必须带选择器，无选择器的样式会作用于所有后代并覆盖按钮配色
        self._force_body.setStyleSheet("QWidget#forceBody { background: transparent; }")
        fb_lay = QVBoxLayout(self._force_body)
        fb_lay.setContentsMargins(0, 2, 0, 0)
        fb_lay.setSpacing(4)

        hint = QLabel("在此添加禁止运行的软件（进程名，如 notepad.exe），运行即被自动终止。")
        hint.setStyleSheet(f"font-size:11px; color:{MUTED};")
        hint.setWordWrap(True)
        fb_lay.addWidget(hint)

        self._force_list = QVBoxLayout()
        self._force_list.setContentsMargins(0, 0, 0, 0)
        self._force_list.setSpacing(3)
        fb_lay.addLayout(self._force_list)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._force_add_btn = QPushButton("＋ 添加")
        self._force_add_btn.setObjectName("accent")
        self._force_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._force_add_btn.clicked.connect(self._add_forbidden_item)
        add_row.addWidget(self._force_add_btn)
        add_row.addStretch(1)
        fb_lay.addLayout(add_row)

        lay.addWidget(self._force_body)
        root.addWidget(card)

        self._force_card = card
        self._force_list_lay = self._force_list
        self._force_body_w = self._force_body
        # 强制拦截通知信号 → 更新状态标签
        self._force_blocked.connect(self._on_force_blocked)
        # 默认折叠
        self._force_expanded = False
        self._force_body.hide()
        self._force_expand_btn.setText("▸ 展开")

        self._refresh_force_ui()

    def _toggle_force_expand(self):
        self._force_expanded = not self._force_expanded
        if self._force_expanded:
            self._force_body.show()
            self._force_expand_btn.setText("▾ 收起")
        else:
            self._force_body.hide()
            self._force_expand_btn.setText("▸ 展开")
        self._apply_size()  # 展开时窗口加高，避免黑名单文字被压缩
        self._refresh_force_ui()

    def _ensure_forced_monitor(self):
        """获取强制模式监控实例：优先复用同进程 app.forced_monitor，否则自建。"""
        app_mon = self._app.forced_monitor if self._app is not None else None
        if app_mon is not None:
            self._forced_monitor = app_mon
            self._self_owned_monitor = False
            return app_mon
        if self._forced_monitor is None:
            try:
                self._forced_monitor = fm.ForcedModeMonitor(
                    forbidden_file=self._forbidden_file,
                    check_interval=1.0,
                    alert_callback=self._on_force_alert_ui,
                )
                self._self_owned_monitor = True
            except Exception as e:
                logger.warning("创建强制模式监控失败: %s", e)
        return self._forced_monitor

    def _on_force_alert_ui(self, process_name: str):
        """强制模式拦截到软件时，通过 Qt 信号安全地从监控线程通知 UI。"""
        self._force_blocked.emit(str(process_name))

    @Slot(str)
    def _on_force_blocked(self, process_name: str):
        """UI 收到拦截通知：把最近拦截的软件记录到 tooltip（主状态每钞轮询刷新）。"""
        now = datetime.now().strftime("%H:%M:%S")
        self._force_status.setToolTip(
            f"最近拦截：{process_name} @ {now}\n禁用进程会自动终止"
        )

    def _is_force_running(self) -> bool:
        mon = self._ensure_forced_monitor()
        if mon is not None:
            try:
                return bool(mon.is_running)
            except Exception:
                pass
        return False

    def _toggle_force_mode(self):
        """开关强制模式（热启停，无需重启程序）。关闭需连续三次弹窗确认。"""
        mon = self._ensure_forced_monitor()
        if mon is None:
            logger.error("无法创建强制模式监控（psutil 未安装？）")
            return
        if mon.is_running:
            # 关闭强制模式：连续三次确认，防误关/一冲动关掉自控
            from PySide6.QtWidgets import QMessageBox
            steps = [
                ("确认关闭强制模式？", "当前强制模式正在运行，将停止自动终止黑名单软件。\n是否确认关闭？"),
                ("二次确认", "真的要关闭吗？关闭后黑名单软件（如游戏）可以自由运行！\n再次确认："),
                ("最后确认", "即将彻底关闭强制模式，确定要停止自控吗？\n（点“否”则保持运行）"),
            ]
            for title, text in steps:
                ret = QMessageBox.question(
                    self, title, text,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ret != QMessageBox.StandardButton.Yes:
                    logger.info("关闭强制模式已取消")
                    return
            # 三次确认通过后：询问多久后自动重新开启
            seconds = self._ask_reopen_delay()
            if seconds is None:
                logger.info("已取消关闭强制模式（未选择自动重开时长）")
                return
            if seconds > 0:
                self._schedule_force_reopen(seconds)
            else:
                self._cancel_force_reopen()
                mon.stop()
        else:
            self._cancel_force_reopen()
            mon.start()
        self._refresh_force_ui(running_only=True)

    def _ask_reopen_delay(self):
        """三次确认后询问“多久后自动重新开启强制模式”。

        返回：None = 用户取消（整体放弃关闭）；
              0 = 不自动开启（永久关闭）；
              >0 = 秒数（到点自动重开）。
        """
        from PySide6.QtWidgets import QInputDialog
        default = f"{int(self._force_reopen_total / 60)}" if self._force_reopen_total else "30"
        text, ok = QInputDialog.getText(
            self,
            "关闭后自动重新开启",
            "关闭后多久自动重新开启强制模式？\n"
            "支持 30=30分钟 / 45m / 1h 30m / 90s。\n"
            "留空 = 不自动开启（永久关闭），取消 = 放弃关闭：",
            text=default,
        )
        if not ok:
            return None
        t = (text or "").strip()
        if not t:
            return 0  # 留空：永久关闭
        seconds = _parse_duration_text(t)
        if seconds is None or seconds <= 0:
            # 无法解析：按不自动开启处理（用户已三次确认要关闭）
            logger.warning("无法解析自动重开时长: %r，按不自动开启处理", t)
            return 0
        return seconds

    def _schedule_force_reopen(self, seconds: int):
        """关闭强制模式并安排在 seconds 秒后自动重新开启。"""
        mon = self._ensure_forced_monitor()
        if mon is not None:
            try:
                mon.stop()
            except Exception:
                pass
        self._force_reopen_at_mono = time.monotonic() + seconds
        self._force_reopen_total = seconds
        self._force_reopen_timer.start(int(seconds * 1000))
        logger.info("强制模式已关闭，将在 %d 秒后自动重新开启", seconds)

    def _cancel_force_reopen(self):
        """取消待执行的自动重开。"""
        try:
            self._force_reopen_timer.stop()
        except Exception:
            pass
        self._force_reopen_at_mono = None
        self._force_reopen_total = 0

    def _reopen_force_mode(self):
        """到时自动重新开启强制模式。"""
        self._force_reopen_at_mono = None
        self._force_reopen_total = 0
        mon = self._ensure_forced_monitor()
        if mon is not None and not mon.is_running:
            try:
                mon.start()
                logger.info("已自动重新开启强制模式")
            except Exception as e:
                logger.error("自动重新开启强制模式失败: %s", e)
        self._refresh_force_ui(running_only=True)

    def _load_forbidden_items(self) -> list:
        return fm.load_forbidden_list(self._forbidden_file)

    def _save_forbidden_items(self, items: list):
        head = "# 禁止运行的软件列表\n# 每行一个进程名（不区分大小写）\n# 以 # 开头的行为注释\n\n"
        try:
            with open(self._forbidden_file, "w", encoding="utf-8") as f:
                f.write(head)
                for it in items:
                    f.write(it + "\n")
        except Exception as e:
            logger.error("保存 forbidden.txt 失败: %s", e)

    def _add_forbidden_item(self):
        from PySide6.QtWidgets import QInputDialog
        items = self._load_forbidden_items()
        text, ok = QInputDialog.getText(
            self, "添加禁止软件",
            "输入进程名（如 notepad.exe，不区分大小写）:",
            text="",
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            return
        for it in items:
            if it.lower().replace(".exe", "") == text.lower().replace(".exe", ""):
                return  # 已存在
        items.append(text)
        self._save_forbidden_items(items)
        # 重新加载黑名单到监控
        mon = self._ensure_forced_monitor()
        if mon is not None:
            try:
                mon.load_list()
            except Exception:
                pass
        self._refresh_force_ui()

    def _remove_forbidden_item(self, item: str):
        items = self._load_forbidden_items()
        items = [it for it in items if it != item]
        self._save_forbidden_items(items)
        mon = self._ensure_forced_monitor()
        if mon is not None:
            try:
                mon.load_list()
            except Exception:
                pass
        self._refresh_force_ui()

    def _refresh_force_ui(self, running_only: bool = False):
        """刷新强制模式卡片显示：状态、开关按钮、黑名单列表。"""
        running = self._is_force_running()
        # running_only 只是跳过列表重建，状态文字里的条数仍需真实数据
        items = self._load_forbidden_items()

        # 状态（拦截历史通过 tooltip 展示，避免每秒轮询覆盖）
        prev_tooltip = self._force_status.toolTip()
        if running:
            self._force_status.setStyleSheet(f"font-size:11px; font-weight:700; color:{ACCENT_DARK};")
            self._force_status.setText(f"🔴 运行中 · {len(items)} 项黑名单")
            self._force_toggle_btn.setText("■ 关闭")
            self._force_toggle_btn.setStyleSheet(
                f"QPushButton {{ background:{ACCENT_DARK}; color:#fff; border:2px solid {BORDER}; border-radius:0px; padding:3px 10px; font-size:11px; font-weight:700; }}"
                f"QPushButton:hover {{ background:{ACCENT}; }}"
            )
        else:
            if self._force_reopen_at_mono is not None:
                # 已关闭，等待自动重新开启：显示倒计时
                remain = max(int(self._force_reopen_at_mono - time.monotonic()), 0)
                h, r = divmod(remain, 3600)
                m, s = divmod(r, 60)
                left = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
                self._force_status.setStyleSheet(f"font-size:11px; font-weight:700; color:{GREEN};")
                self._force_status.setText(f"⏳ 已关闭 · {left} 后自动开启 · {len(items)} 项")
            else:
                self._force_status.setStyleSheet(f"font-size:11px; font-weight:700; color:{MUTED};")
                self._force_status.setText(f"⚪ 未开启 · {len(items)} 项黑名单")
            self._force_toggle_btn.setText("开启")
            self._force_toggle_btn.setStyleSheet(
                f"QPushButton {{ background:{GREEN}; color:#fff; border:2px solid {BORDER}; border-radius:0px; padding:3px 10px; font-size:11px; font-weight:700; }}"
                f"QPushButton:hover {{ background:#37b24d; }}"
            )
        if prev_tooltip:
            self._force_status.setToolTip(prev_tooltip)

        if running_only:
            return  # 轮询只需更新状态，不必重建黑名单列表

        # 黑名单列表（重建）
        while self._force_list_lay.count():
            it = self._force_list_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

        if not items:
            empty = QLabel("（空）点击“添加”加入要禁止的软件")
            empty.setStyleSheet(f"font-size:11px; color:{MUTED};")
            self._force_list_lay.addWidget(empty)
        else:
            for it in items:
                row = QWidget()
                row.setObjectName("forceRow")
                row.setStyleSheet("QWidget#forceRow { background: transparent; }")
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(6)
                dot = QLabel("●")
                dot.setStyleSheet(f"color:{ACCENT}; font-size:10px;")
                name = QLabel(it)
                name.setStyleSheet("font-size:12px;")
                name.setToolTip(f"禁止运行 {it}")
                rm = QPushButton("✕")
                rm.setObjectName("ghost")
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.setToolTip(f"从黑名单移除 {it}")
                rm.setStyleSheet(
                    f"QPushButton {{ background:transparent; color:{MUTED}; padding:1px 6px; font-size:11px; }}"
                    f"QPushButton:hover {{ color:{ACCENT}; }}"
                )
                rm.clicked.connect(lambda _, x=it: self._remove_forbidden_item(x))
                rl.addWidget(dot)
                rl.addWidget(name, 1)
                rl.addWidget(rm)
                self._force_list_lay.addWidget(row)

    # 周期轮询强制模式状态（结合模式 + UI 独立运行都在用）
    def _poll_force_status(self):
        if getattr(self, "_force_card", None) is None:
            return
        self._refresh_force_ui(running_only=True)

    def _panel(self) -> QFrame:
        f = QFrame(self)
        f.setObjectName("panel")
        # 内容固定高度的卡片不允许被垂直压缩，否则窗口空间不足时文字会被切成半截
        f.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        return f

    def _ghost_btn(self, text, handler, tooltip=""):
        b = QPushButton(text)
        b.setObjectName("ghost")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tooltip)
        b.clicked.connect(handler)
        return b

    def _build_pomodoro(self):
        self._update_pomo_labels()
        self._update_scope_buttons()
        self._update_link_btn()
        self._update_mode_buttons()

    # ---------- 窗口行为 ----------
    def _on_header_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _on_header_move(self, event):
        if hasattr(self, "_drag_offset") and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _toggle_topmost(self):
        self._topmost = not self._topmost
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._topmost)
        self.show()
        self._pin_btn.setText("📌" if self._topmost else "📍")
        if self._topmost:
            self._reassert_topmost()

    def _reassert_topmost(self):
        """用 Win32 SetWindowPos 重新声明置顶。

        窗口的 WindowStaysOnTopHint 只在创建时设置一次；之后若有其他置顶窗口
        （如无框游戏、其他工具的置顶面板）出现，可能把本面板压在下面。每秒
        重新声明一次可抢回顶层。注意：对真正的独占全屏（Exclusive Fullscreen）
        游戏无效——那是显卡直接出图，任何普通窗口都无法覆盖，游戏需改成
        无边框窗口化模式。
        """
        if not self._topmost or _SWP is None:
            return
        try:
            _SWP(int(self.winId()), _HWND_TOPMOST, 0, 0, 0, 0, _SWP_FLAGS)
        except Exception:
            pass

    def _open_cards_folder(self):
        """一键打开卡片文件夹（data/cards），不存在则先创建。"""
        try:
            p = Path(self._data_dir) / "cards"
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))  # Windows：资源管理器打开
            logger.info("已打开卡片文件夹: %s", p)
        except Exception as e:
            logger.warning("打开卡片文件夹失败: %s", e)

    # ---------- 淡化模式（goldfish 式：空闲淡化看背景，交互恢复） ----------
    def _toggle_fade(self):
        self._fade_mode = not self._fade_mode
        if self._fade_mode:
            self._set_fade_opacity(self._fade_opacity)
            self._fade_btn.setObjectName("ghostActive")
            self._fade_btn.setToolTip("淡化模式已开启：鼠标移入恢复，移出自动淡化")
        else:
            self._set_fade_opacity(1.0)
            self._fade_btn.setObjectName("ghost")
            self._fade_btn.setToolTip("淡化模式：窗口半透明，可看到后面的内容")
        self._fade_btn.style().unpolish(self._fade_btn)
        self._fade_btn.style().polish(self._fade_btn)

    def _set_fade_opacity(self, value: float):
        """平滑过渡到指定窗口透明度。"""
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(180)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(value)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim  # 持有引用防止被回收

    def enterEvent(self, event):
        if self._fade_mode:
            # 鼠标移入：恢复实色便于操作
            self._set_fade_opacity(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._fade_mode:
            # 鼠标移出：回到淡化，透出背景
            self._set_fade_opacity(self._fade_opacity)
        super().leaveEvent(event)

    def _toggle_mini(self):
        self._mini = not self._mini
        if self._mini:
            self._hist_card.hide()
            self._rank_card.hide()
            self._force_card.hide()
            self._footer.hide()
            self._cards_btn.hide()
            self._mini_btn.setText("□ 展开")
            self._mini_btn.setToolTip("展开完整面板")
            # 窄窗口下缩短标题、隐藏轮次信息，避免文字被截断
            self._title_label.setText("🍅 番茄钟")
            self._round_label.hide()
            self._mon_txt.hide()
        else:
            self._hist_card.show()
            self._rank_card.show()
            self._force_card.show()
            self._footer.show()
            self._cards_btn.show()
            self._mini_btn.setText("─")
            self._mini_btn.setToolTip("最小化（只显示番茄钟和当前事件）")
            self._title_label.setText("🍅 番茄钟悬浮面板")
            self._round_label.show()
            if self._app is not None:
                self._mon_txt.show()
        self._apply_size()

    def closeEvent(self, event):
        self._cleanup()
        event.accept()
        # 本窗口是 Qt.Tool 类型：关闭它不会触发 quitOnLastWindowClosed，
        # 必须显式退出事件循环，否则窗口消失但进程（含后台监控）残留。
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.quit()
        super().closeEvent(event)

    def _cleanup(self):
        """停止定时器与数据线程（窗口关闭 / 应用退出时调用）。"""
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        try:
            self._watch.stop()
        except Exception:
            pass
        try:
            self._pomo_tick.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_mon_timer", None) is not None:
                self._mon_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_live_tick", None) is not None:
                self._live_tick.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_force_timer", None) is not None:
                self._force_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_force_reopen_timer", None) is not None:
                self._force_reopen_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_top_timer", None) is not None:
                self._top_timer.stop()
        except Exception:
            pass
        # 停止 overlay 自建的强制模式监控（若复用 app 的 monitor 或未自建则跳过）
        if self._self_owned_monitor and self._forced_monitor is not None:
            try:
                self._forced_monitor.stop()
            except Exception:
                pass
        try:
            if getattr(self, "_fade_anim", None) is not None:
                self._fade_anim.stop()
        except Exception:
            pass
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    # ---------- 监控状态（结合模式） ----------
    def _poll_monitor_status(self):
        if self._app is None:
            return
        try:
            st = self._app.get_status()
            if st.get("running"):
                sched = st.get("scheduler") or {}
                self._mon_dot.setStyleSheet(f"color:{GREEN}; font-size:10px;")
                parts = ["监控中"]
                interval = sched.get("interval")
                if interval:
                    parts.append(f"每{interval}s")
                last = sched.get("last_run_time")
                if last:
                    parts.append(f"上次{str(last)[11:16]}")
                self._mon_txt.setText(" · ".join(parts))
                self._mon_txt.setToolTip(
                    f"运行模式: {st.get('mode', '')}"
                    + (" · 强制模式" if st.get("force_mode") else "")
                )
            else:
                self._mon_dot.setStyleSheet(f"color:{MUTED}; font-size:10px;")
                self._mon_txt.setText("监控未运行")
                self._mon_txt.setToolTip("")
        except Exception as e:
            logger.debug("读取监控状态失败: %s", e)

    # ---------- 计时器（番茄钟 / 倒计时 / 秒表） ----------
    def _set_mode(self, mode: str):
        """切换计时模式：pomodoro / countdown / stopwatch。"""
        if mode == self._mode:
            return
        self._pomo_tick.stop()
        self._running = False
        self._mode = mode
        self._overflow = False
        self._direction = "down"
        self._start_btn.setText("▶ 开始")
        if mode == "pomodoro":
            self._phase = "work"
            self._phase_index = 0
            self._remaining = self._pomo_times[0] if self._pomo_times else self._work_sec
        elif mode == "countdown":
            self._remaining = self._countdown_sec
        else:  # stopwatch
            self._direction = "up"
            self._remaining = 0
        self._update_mode_buttons()
        self._update_pomo_labels()

    def _update_mode_buttons(self):
        for btn, m in ((self._mode_btn_pomodoro, "pomodoro"),
                       (self._mode_btn_countdown, "countdown"),
                       (self._mode_btn_stopwatch, "stopwatch")):
            btn.setObjectName("ghostActive" if self._mode == m else "ghost")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_time_click(self, event):
        """点击大时间数字：倒计时模式设置时长（Catime 式输入）。"""
        if event.button() == Qt.MouseButton.LeftButton and self._mode == "countdown":
            self._set_countdown_duration()

    def _set_countdown_duration(self):
        from PySide6.QtWidgets import QInputDialog
        current_hint = str(int(self._countdown_sec / 60)) if self._countdown_sec % 60 == 0 else str(self._countdown_sec)
        text, ok = QInputDialog.getText(
            self,
            "设置倒计时",
            "时长（支持 25=25分钟 / 90s / 1h 30m / 130 20=130分20秒）:",
            text=current_hint,
        )
        if not ok:
            return
        seconds = _parse_duration_text(text)
        if seconds is None or seconds <= 0:
            return
        was_running = self._running
        self._pomo_tick.stop()
        self._running = False
        self._countdown_sec = seconds
        self._remaining = seconds
        self._overflow = False
        self._direction = "down"
        self._start_btn.setText("▶ 开始")
        if was_running:
            self._toggle_running()
        self._update_pomo_labels()

    def _toggle_running(self):
        if self._running:
            self._pomo_tick.stop()
            self._running = False
            self._start_btn.setText("▶ 继续")
        else:
            # 防漂移基准：恢复/开始时记录单调时钟与当时值
            self._base_mono = time.monotonic()
            self._base_value = self._remaining if self._direction == "down" else 0
            self._running = True
            self._pomo_tick.start()
            self._start_btn.setText("⏸ 暂停")

    def _reset_pomo(self):
        self._pomo_tick.stop()
        self._running = False
        self._overflow = False
        self._direction = "down"
        self._rounds_done = 0
        if self._mode == "pomodoro":
            self._phase = "work"
            self._phase_index = 0
            self._remaining = self._pomo_times[0] if self._pomo_times else self._work_sec
        elif self._mode == "countdown":
            self._remaining = self._countdown_sec
        else:
            self._direction = "up"
            self._remaining = 0
        self._start_btn.setText("▶ 开始")
        self._update_pomo_labels()

    def _skip_pomo(self):
        was_running = self._running
        self._pomo_tick.stop()
        if self._mode == "pomodoro":
            self._advance_pomodoro()
            if was_running:
                # 重新锚定防漂移基准
                self._base_mono = time.monotonic()
                self._base_value = self._remaining
                self._pomo_tick.start()
            self._update_pomo_labels()
        elif self._mode == "countdown":
            # 跳过 = 立即到点：响铃 + 超时动作 + 转正计时
            QApplication.beep()
            self._fire_timeout_action()
            self._direction = "up"
            self._remaining = 0
            self._overflow = True
            if was_running:
                self._base_mono = time.monotonic()
                self._base_value = 0
                self._pomo_tick.start()
            self._update_pomo_labels()
        else:  # stopwatch：跳过 = 归零继续
            self._remaining = 0
            self._update_pomo_labels()

    def _on_pomo_tick(self):
        if not self._running:
            return
        # 防漂移：按单调时钟真实流逝计算（Catime QueryPerformanceCounter 思路）
        elapsed = int(time.monotonic() - self._base_mono)
        if self._direction == "up":
            self._remaining = elapsed
            self._update_pomo_labels()
            return
        self._remaining = max(self._base_value - elapsed, 0)
        if self._remaining <= 0:
            self._remaining = 0
            self._update_pomo_labels()
            self._handle_timeout()
            return
        self._update_pomo_labels()

    def _handle_timeout(self):
        """到点处理：响铃 + 超时动作 + 阶段推进/转正计时 + 重新锚定防漂移基准。"""
        QApplication.beep()
        self._fire_timeout_action()  # 到时超时动作（打开网站）
        if self._mode == "pomodoro":
            self._advance_pomodoro()
        else:  # 倒计时到 0 → 自动转正计时（Catime COUNT_UP 溢出）
            self._direction = "up"
            self._remaining = 0
            self._overflow = True
        # 重新锚定防漂移基准（阶段切换/转正计时后从新值开始计）
        self._base_mono = time.monotonic()
        self._base_value = self._remaining if self._direction == "down" else 0
        self._update_pomo_labels()

    def _advance_pomodoro(self):
        if self._pomo_times:
            # 自定义阶段序列：按序轮转，最后一阶段后回到起点
            self._phase_index += 1
            if self._phase_index >= len(self._pomo_times):
                self._phase_index = 0
                self._rounds_done += 1
            if self._phase_index % 2 == 0:
                self._phase = "work"
            elif self._phase_index == len(self._pomo_times) - 1 and len(self._pomo_times) > 2:
                self._phase = "long_break"
            else:
                self._phase = "break"
            self._remaining = self._pomo_times[self._phase_index]
        else:
            # 传统 25/5/15 + 轮次逻辑
            if self._phase == "work":
                self._rounds_done += 1
                if self._rounds_target > 0 and self._rounds_done % self._rounds_target == 0:
                    self._phase = "long_break"
                    self._remaining = self._long_break_sec
                else:
                    self._phase = "break"
                    self._remaining = self._break_sec
            else:
                self._phase = "work"
                self._remaining = self._work_sec

    # ---------- 到时超时动作：打开网站 ----------
    def _set_timeout_website(self):
        """点击 🔗：设置到点自动打开的网址（留空清除）。"""
        from PySide6.QtWidgets import QInputDialog
        current = self._timeout_website
        url, ok = QInputDialog.getText(
            self,
            "到时打开网站",
            "倒计时到 0 时自动用浏览器打开（留空=关闭该功能）:",
            text=current,
        )
        if not ok:
            return
        url = url.strip()
        self._timeout_website = url
        self._save_ui_state()
        self._update_link_btn()

    def _update_link_btn(self):
        if self._timeout_website:
            self._link_btn.setStyleSheet(
                f"QPushButton {{ background: {YELLOW}; color: {TEXT}; border: 2px solid {BORDER}; padding: 2px 8px; font-size: 12px; font-weight: 700; }}"
                f"QPushButton:hover {{ background: {YELLOW_HOVER}; }}"
            )
            self._link_btn.setToolTip(f"到时打开: {self._timeout_website}（点击修改）")
        else:
            self._link_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {MUTED}; border: 2px solid transparent; padding: 2px 8px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {YELLOW}; border: 2px solid {BORDER}; color: {TEXT}; }}"
            )
            self._link_btn.setToolTip("到时自动打开网站（点击设置网址）")

    def _save_ui_state(self):
        """把面板内可修改的设置持久化到 data/ui_state.json。"""
        try:
            import json as _json
            state = {
                "timeout_website": self._timeout_website,
                "current_task": self._task_text,
            }
            self._ui_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._ui_state_path.write_text(
                _json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("面板设置已保存: %s", self._ui_state_path)
        except Exception as e:
            logger.warning("保存面板设置失败: %s", e)

    def _fire_timeout_action(self):
        """阶段/倒计时到 0 时触发：打开配置的网站。"""
        url = self._timeout_website
        if not url:
            return
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            os.startfile(url)  # 系统默认浏览器打开
            logger.info("⏰ 到时打开网站: %s", url)
        except Exception as e:
            logger.warning("打开网站失败: %s", e)

    def _update_pomo_labels(self):
        # 时间数字：自适应格式，倒计时溢出显示 + 前缀
        prefix = "+" if (self._mode == "countdown" and self._overflow and self._direction == "up") else ""
        self._pomo_time.setText(prefix + _fmt_time(self._remaining))
        if self._mode == "stopwatch":
            self._pomo_time.setStyleSheet(f"font-size:36px; font-weight:800; color:{GREEN};")
        else:
            self._pomo_time.setStyleSheet(f"font-size:36px; font-weight:800; color:{ACCENT};")

        # 阶段/模式标签
        if self._mode == "pomodoro":
            self._phase_label.setText(PHASE_NAMES.get(self._phase, self._phase))
            phase_color = ACCENT if self._phase == "work" else GREEN
            self._phase_label.setStyleSheet(f"font-size:12px; font-weight:800; color:{phase_color};")
        elif self._mode == "countdown":
            self._phase_label.setText("⏳ 倒计时" + ("（超时中）" if self._overflow else ""))
            self._phase_label.setStyleSheet(f"font-size:12px; font-weight:800; color:{ACCENT};")
        else:
            self._phase_label.setText("⏱ 秒表")
            self._phase_label.setStyleSheet(f"font-size:12px; font-weight:800; color:{GREEN};")

        # 进度条：倒计时方向显示剩余进度；秒表隐藏
        if self._mode == "stopwatch":
            self._pomo_bar.hide()
        else:
            self._pomo_bar.show()
            if self._mode == "pomodoro":
                total = (self._pomo_times[self._phase_index] if self._pomo_times
                         else {"work": self._work_sec, "break": self._break_sec,
                               "long_break": self._long_break_sec}[self._phase])
            else:
                total = self._countdown_sec
            self._pomo_bar.setRange(0, max(total, 1))
            self._pomo_bar.setValue(total - self._remaining)

        # 右侧信息
        if self._mode == "pomodoro":
            if self._pomo_times:
                self._round_label.setText(
                    f"🍅 ×{self._rounds_done} · 阶段 {self._phase_index + 1}/{len(self._pomo_times)}"
                )
            elif self._rounds_target > 0:
                self._round_label.setText(f"🍅 ×{self._rounds_done} · 第 {(self._rounds_done % self._rounds_target) + 1}/{self._rounds_target} 轮")
            else:
                self._round_label.setText(f"🍅 ×{self._rounds_done}")
        elif self._mode == "countdown":
            self._round_label.setText("点击时间设时长")
        else:
            self._round_label.setText("")

    # ---------- 数据刷新 ----------
    def _check_data_file(self):
        try:
            p = Path(self._data_dir) / "cards.json"
            if p.exists():
                mtime = p.stat().st_mtime_ns
                size = p.stat().st_size
                if mtime != self._last_mtime or size != self._last_size:
                    self._last_mtime = mtime
                    self._last_size = size
                    self._reload_request.emit(self._scope)
                    return
            # 前台应用切换：app_state.json 中应用/离开状态变化时立即刷新，
            # 新卡片落地前先把应用行翻转并进入“分析中”过渡态
            sp = Path(self._data_dir) / "app_state.json"
            if sp.exists():
                try:
                    import json as _json
                    st = _json.loads(sp.read_text(encoding="utf-8"))
                    key = (str(st.get("app") or "").lower(), bool(st.get("is_idle")))
                    if self._last_app_key is not None and key != self._last_app_key:
                        self._reload_request.emit(self._scope)
                    self._last_app_key = key
                except Exception:
                    pass
        except Exception:
            pass

    def _set_scope(self, scope: str):
        self._scope = scope
        self._update_scope_buttons()
        self._reload_request.emit(scope)

    def _update_scope_buttons(self):
        for btn, s in ((self._scope_today, "today"), (self._scope_week, "week"), (self._scope_all, "all")):
            btn.setObjectName("ghostActive" if self._scope == s else "ghost")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    @Slot(object)
    def _apply_view(self, view: dict):
        self._view = view
        now = datetime.now()

        # 当前事件
        cur = view["current"]
        cur_app = view.get("current_app") or {}

        # 应用行：当前前台应用别名 / 离开状态（无应用数据时隐藏）
        if cur_app.get("app"):
            alias = str(cur_app.get("alias") or cur_app["app"])
            self._cur_app.setText(alias)
            tip = str(cur_app["app"])
            if cur_app.get("title"):
                tip += f" · {cur_app['title']}"
            self._cur_app.setToolTip(tip)
            self._cur_app.setStyleSheet(f"font-size:14px; font-weight:800; color:{TEXT};")
            self._cur_app.show()
        elif cur_app.get("is_idle"):
            self._cur_app.setText("💤 离开中")
            self._cur_app.setToolTip("未检测到键盘鼠标操作，统计已暂停")
            self._cur_app.setStyleSheet(f"font-size:14px; font-weight:800; color:{MUTED};")
            self._cur_app.show()
        else:
            self._cur_app.hide()

        if cur:
            desc = str(cur.get("description") or "未知活动")
            cat = str(cur.get("category") or "其他")
            # 过渡态：最新卡片属于上一个应用（新应用的卡片还在截图分析中）
            stale = bool(
                cur_app.get("app") and cur.get("app")
                and str(cur["app"]).lower() != str(cur_app["app"]).lower()
            )
            if stale:
                self._cur_desc.setText(f"⏳ 分析中…（上一活动：{desc}）")
                self._cur_desc.setStyleSheet(f"font-size:13px; font-weight:700; color:{MUTED};")
            else:
                self._cur_desc.setText(desc)
                self._cur_desc.setStyleSheet("")  # 恢复 QSS 中的 curDesc 样式
            self._cur_desc.setToolTip(desc)
            self._cur_chip.setText(cat)
            self._cur_chip.setStyleSheet(
                f"QPushButton#chip {{ background:{_cat_color(cat)}; color:{TEXT}; border:2px solid {BORDER}; border-radius:0px; padding:2px 9px; font-size:11px; font-weight:700; }}"
            )
            # 已持续：优先按应用会话起点（精确），否则按卡片时间（估算）
            start_dt = None
            if cur_app.get("app") and cur_app.get("start"):
                try:
                    start_dt = datetime.fromisoformat(str(cur_app["start"]))
                except Exception:
                    start_dt = None
            if start_dt is None:
                start_dt = stats._parse_dt(cur)
            if cur_app.get("is_idle") and not cur_app.get("app"):
                self._cur_meta.setText("已离开，统计暂停")
            elif start_dt is not None:
                elapsed = max((now - start_dt).total_seconds(), 0)
                self._cur_meta.setText(
                    f"开始于 {start_dt.strftime('%H:%M')} · 已持续 {stats.format_duration(min(elapsed, 24 * 3600))}"
                )
            else:
                self._cur_meta.setText("开始时间未知")
        else:
            self._cur_desc.setText("暂无记录")
            self._cur_chip.setText("其他")
            self._cur_chip.setStyleSheet("")
            self._cur_meta.setText("等待监控产生记录…")

        # 最近事件
        self._clear_history()
        for card in view["history"]:
            row = HistoryRow(card, self._font)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self._hist_list.addItem(item)
            self._hist_list.setItemWidget(item, row)

        # 时间排名
        self._clear_rank()
        self._rank_rows = []
        ranking = view["ranking"]
        if ranking:
            for r in ranking:
                row = RankRow(r, self._font)
                self._rank_rows.append(row)
                self._rank_box.addWidget(row)
        else:
            self._rank_box.addWidget(self._rank_empty)

        # 页脚
        scope_txt = {"today": "今日", "week": "本周", "all": "全部"}.get(view["scope"], view["scope"])
        total_txt = stats.format_duration(view["total_seconds"])
        self._footer.setText(
            f"数据更新 {view['updated_at']} · {scope_txt}卡片 {view['card_count']} 张 · 累计 {total_txt}"
        )

    def _clear_history(self):
        for i in range(self._hist_list.count()):
            it = self._hist_list.item(i)
            w = self._hist_list.itemWidget(it)
            if w is not None:
                self._hist_list.setItemWidget(it, None)
                w.deleteLater()
        self._hist_list.clear()

    def _clear_rank(self):
        while self._rank_box.count():
            item = self._rank_box.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._rank_empty:
                w.deleteLater()

    # ---------- 实时心跳 ----------
    def _tick_live(self):
        """每秒滚动更新：当前事件“已持续” + 排名中当前条目的累计时长。

        不重读数据文件：以 build 时的 open 时长为基准做增量更新，
        直到下一次刷新（新卡片产生 / 应用会话切换）重新固化。
        计时起点优先取应用会话开始时间（AppObserver，精确、不封顶），
        否则回退到最后一张卡片时间（估算，封顶 cap）。
        """
        view = self._view
        if not view:
            return
        live = view.get("live")
        if not live:
            return

        cur_app = view.get("current_app") or {}
        if cur_app.get("is_idle") and not cur_app.get("app"):
            self._cur_meta.setText("已离开，统计暂停")
            return

        # 解析计时起点
        base_dt = None
        uncapped = False
        if live.get("app_start"):
            try:
                base_dt = datetime.fromisoformat(str(live["app_start"]))
                uncapped = True  # 应用会话时长是真实时长，不封顶
            except Exception:
                base_dt = None
        if base_dt is None:
            s = str(live.get("last_card_dt") or "")
            if not s:
                return
            try:
                base_dt = datetime.fromisoformat(s) if "T" in s else datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return

        real_elapsed = max((datetime.now() - base_dt).total_seconds(), 0.0)
        open_sec = real_elapsed if uncapped else min(real_elapsed, self._cap_seconds)
        delta = open_sec - live.get("open_at_build", open_sec)
        live["open_at_build"] = open_sec
        live["open_seconds"] = open_sec

        # 当前事件“已持续”（真实时长，不封顶到排名上限）
        cur = view.get("current")
        if cur:
            self._cur_meta.setText(
                f"开始于 {base_dt.strftime('%H:%M')} · 已持续 {stats.format_duration(min(real_elapsed, 24 * 3600))}"
            )

        # 排名中当前事件分组实时增长
        idx = live.get("current_rank_index", -1)
        if 0 <= idx < len(view["ranking"]) and idx < len(self._rank_rows):
            r = view["ranking"][idx]
            r["total"] = max(r["total"] + delta, 0.0)
            denom = max(view.get("total_seconds", 1.0), 1.0)
            r["share"] = r["total"] / denom
            self._rank_rows[idx].update_item(r)


# ---------- 入口 ----------
def run_overlay(config: dict, data_dir: str = "data", app=None) -> int:
    """启动悬浮面板（阻塞直到窗口关闭）。

    app: 可选，同进程监控实例（Application）。传入后面板顶部显示监控状态
    （start --ui 结合模式）；独立运行（python main.py ui）时传 None。
    """
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    qapp.setStyle("Fusion")
    qapp.setFont(QFont("Microsoft YaHei UI", 10))

    window = OverlayWindow(config, data_dir, app=app)
    window.show()
    qapp.aboutToQuit.connect(window._cleanup)
    return qapp.exec()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(run_overlay({}, "data"))
