import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil 库未安装，强制模式将无法使用。请运行: pip install psutil")


def load_forbidden_list(file_path: str) -> list:
    forbidden = []
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"forbidden.txt 未找到: {file_path}，将创建默认文件")
        _create_default_forbidden_file(file_path)
        path = Path(file_path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    forbidden.append(line)
        logger.debug(f"从 {file_path} 加载了 {len(forbidden)} 条禁止规则")
    except Exception as e:
        logger.error(f"读取 forbidden.txt 失败: {e}")

    return forbidden


def _create_default_forbidden_file(file_path: str):
    default_content = """# 禁止运行的软件列表
# 每行一个进程名（不区分大小写），支持 .exe 后缀或不带后缀
# 以 # 开头的行为注释

# 示例（请根据实际需要修改）：
# notepad.exe
# mspaint.exe
# calc.exe
"""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(default_content)
        logger.info(f"已创建默认 forbidden.txt: {file_path}")
    except Exception as e:
        logger.error(f"创建 forbidden.txt 失败: {e}")


def _normalize_name(name: str) -> str:
    return name.lower().replace(".exe", "").strip()


class ForcedModeMonitor:
    def __init__(self, forbidden_file: str = "forbidden.txt", check_interval: float = 1.0,
                 alert_callback=None, reload_interval: float = 10.0):
        self.forbidden_file = forbidden_file
        self.check_interval = check_interval
        self.reload_interval = reload_interval
        self.alert_callback = alert_callback
        self._forbidden_list = []
        self._forbidden_set = set()
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._enabled = False
        self._killed_pids = set()
        self._last_reload = 0.0
        self._last_alert_time = 0.0
        self._blocked_count = 0
        self._last_blocked_process = ""
        self._scan_count = 0

    def load_list(self) -> list:
        self._forbidden_list = load_forbidden_list(self.forbidden_file)
        self._forbidden_set = {_normalize_name(name) for name in self._forbidden_list if _normalize_name(name)}
        self._last_reload = time.time()
        logger.info(f"已加载禁止列表: {len(self._forbidden_list)} 个条目")
        if self._forbidden_list:
            for item in self._forbidden_list:
                logger.info(f"  - {item}")
        return self._forbidden_list

    def start(self):
        if not PSUTIL_AVAILABLE:
            logger.error("psutil 未安装，无法启动强制模式")
            return

        with self._lock:
            if self._running:
                logger.warning("强制模式监控已在运行中")
                return

            self._running = True
            self._enabled = True
            self._killed_pids.clear()
            self._blocked_count = 0
            self._last_blocked_process = ""
            self._scan_count = 0
            self.load_list()

            if not self._forbidden_list:
                logger.warning("禁止列表为空，强制模式监控已启动但不会阻止任何软件")

            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
            logger.info(f"强制模式监控已启动，检查间隔: {self.check_interval}s, 重载间隔: {self.reload_interval}s")

    def stop(self):
        with self._lock:
            self._running = False
            self._enabled = False
            logger.info(f"强制模式监控已停止，共拦截: {self._blocked_count} 次")

    def _matches_forbidden(self, proc_name: str):
        if not proc_name or not self._forbidden_set:
            return None
        norm_name = _normalize_name(proc_name)
        if norm_name in self._forbidden_set:
            return proc_name
        for forbidden_name in self._forbidden_list:
            norm_forbidden = _normalize_name(forbidden_name)
            if not norm_forbidden:
                continue
            if norm_name.startswith(norm_forbidden + "_") or norm_name.startswith(norm_forbidden + " "):
                return forbidden_name
        return None

    def _cleanup_killed_pids(self):
        alive = set()
        for pid in list(self._killed_pids):
            try:
                if psutil.pid_exists(pid):
                    alive.add(pid)
            except Exception:
                pass
        self._killed_pids = alive

    def _monitor_loop(self):
        logger.info("强制模式监控循环开始")

        while self._running:
            self._scan_count += 1
            try:
                now = time.time()
                if now - self._last_reload >= self.reload_interval:
                    self.load_list()

                if self._scan_count % 300 == 0:
                    self._cleanup_killed_pids()

                if not self._forbidden_set:
                    time.sleep(self.check_interval)
                    continue

                for proc in psutil.process_iter(["pid", "name"]):
                    if not self._running:
                        break
                    try:
                        proc_name = proc.info.get("name", "")
                        if not proc_name:
                            try:
                                proc_name = proc.name()
                            except Exception:
                                continue

                        matched = self._matches_forbidden(proc_name)
                        if matched:
                            pid = proc.info["pid"]
                            if pid not in self._killed_pids and (now - self._last_alert_time) > 0.5:
                                logger.warning(f"检测到禁止软件: {proc_name} (PID: {pid}) 匹配规则: {matched}")

                                if self.alert_callback:
                                    try:
                                        self.alert_callback(proc_name)
                                    except Exception as e:
                                        logger.error(f"弹窗回调失败: {e}")

                                self._last_alert_time = now

                            try:
                                p = psutil.Process(pid)
                                p.kill()
                                if pid not in self._killed_pids:
                                    self._killed_pids.add(pid)
                                    self._blocked_count += 1
                                    self._last_blocked_process = proc_name
                                    logger.info(f"已终止进程: {proc_name} (PID: {pid}) 累计拦截: {self._blocked_count}")
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass

                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

            except Exception as e:
                logger.error(f"强制模式监控异常: {e}")
                import traceback
                traceback.print_exc()

            time.sleep(self.check_interval)

        logger.info("强制模式监控循环结束")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def forbidden_list(self) -> list:
        return self._forbidden_list.copy()

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "enabled": self._enabled,
            "forbidden_count": len(self._forbidden_list),
            "forbidden_items": self._forbidden_list.copy(),
            "killed_today": len(self._killed_pids),
            "blocked_count": self._blocked_count,
            "last_blocked_process": self._last_blocked_process,
            "check_interval": self.check_interval
        }
