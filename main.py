"""屏幕监管系统主入口（命令行版本）"""
import argparse
import logging
import os
import sys
import threading
import signal
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# PyInstaller 打包后，切换工作目录到 exe 所在目录，确保 config.yaml / data / logs 能被找到
if getattr(sys, 'frozen', False):
    os.chdir(Path(sys.executable).parent)

from src.config_loader import ConfigLoader
from src.scheduler import ScreenMonitorScheduler
from src.forced_mode import ForcedModeMonitor, PSUTIL_AVAILABLE


_running_instance = None


def _load_forbidden_from_file(file_path: str) -> list:
    items = []
    try:
        p = Path(file_path)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        items.append(line)
    except Exception:
        pass
    return items


def _save_forbidden_to_file(file_path: str, items: list) -> None:
    header = "# 禁止运行的软件列表\n# 每行一个进程名（不区分大小写）\n# 以 # 开头的行为注释\n\n"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(header)
            for item in items:
                f.write(item + "\n")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"保存 forbidden.txt 失败: {e}")


def setup_logging(log_dir: str = "logs") -> None:
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    log_file = log_path / "screen_monitor.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    file_handler.suffix = "%Y-%m-%d"

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def parse_args():
    parser = argparse.ArgumentParser(
        description="屏幕监管系统 - 定时截图并分析用户活动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                        # 一键启动：监控 + 悬浮面板
  python main.py start                   # 启动持续监控（打开配置面板）
  python main.py start --mode record     # 以记录模式直接启动
  python main.py start --mode learning   # 以学习模式直接启动
  python main.py start --ui              # 监控 + 悬浮面板一体启动
  python main.py once                    # 执行一次截图分析
  python main.py stop                    # 停止运行中的监控
  python main.py report                  # 生成今日报告
  python main.py report --date 2026-03-30  # 生成指定日期报告
  python main.py ui                      # 打开系统最顶层悬浮面板（番茄钟+事件+排名）
  python main.py --install-autostart     # 安装开机自启动
  python main.py --uninstall-autostart   # 卸载开机自启动
  python main.py --config custom.yaml start  # 使用指定配置文件
        """
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="start",
        choices=["start", "stop", "once", "report", "ui"],
        help="操作命令: start(启动), stop(停止), once(执行一次), report(生成报告), ui(打开悬浮面板)"
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="配置文件路径 (默认: 自动查找 config.yaml)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细日志"
    )

    parser.add_argument(
        "--date", "-d",
        type=str,
        default=None,
        help="报告日期 (格式: YYYY-MM-DD，默认今日)"
    )

    parser.add_argument(
        "--mode", "-m",
        type=str,
        default=None,
        choices=["record", "learning"],
        help="运行模式: record(记录), learning(学习)。指定后将跳过配置面板"
    )

    parser.add_argument(
        "--force-mode",
        action="store_true",
        help="启用强制模式（需配合 --mode 使用）"
    )

    parser.add_argument(
        "--ui",
        action="store_true",
        help="start 时同时启动悬浮面板（监控+面板一体运行，关闭面板即停止监控）"
    )

    parser.add_argument(
        "--install-autostart",
        action="store_true",
        help="安装开机自启动"
    )

    parser.add_argument(
        "--uninstall-autostart",
        action="store_true",
        help="卸载开机自启动"
    )

    return parser.parse_args()


def _get_startup_folder() -> Path:
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-Command", "[Environment]::GetFolderPath('Startup')"],
            capture_output=True, text=True
        )
        startup_path = result.stdout.strip()
        if startup_path and Path(startup_path).exists():
            return Path(startup_path)
    except Exception:
        pass

    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup


def install_autostart() -> bool:
    logger = logging.getLogger(__name__)
    startup_folder = _get_startup_folder()
    if not startup_folder.exists():
        logger.error(f"启动文件夹不存在: {startup_folder}")
        return False
    script_dir = Path(__file__).parent.resolve()
    main_py = script_dir / "main.py"
    # 优先用 pythonw.exe（无控制台窗口），找不到则用当前解释器
    python_exe = sys.executable
    pythonw_exe = Path(python_exe).with_name("pythonw.exe")
    if pythonw_exe.exists():
        python_exe = str(pythonw_exe)
    vbs_path = startup_folder / "屏幕监管系统.vbs"
    vbs_content = f'''Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = "{script_dir}"
ws.Run """{python_exe}"" ""{main_py}"" start --mode record --force-mode --ui", 1, False
Set ws = Nothing
'''
    try:
        with open(vbs_path, "w", encoding="gbk") as f:
            f.write(vbs_content)
        logger.info("开机自启动已安装成功!")
        logger.info(f"启动脚本位置: {vbs_path}")
        return True
    except Exception as e:
        logger.error(f"安装开机自启动失败: {e}")
        return False


def uninstall_autostart() -> bool:
    logger = logging.getLogger(__name__)
    startup_folder = _get_startup_folder()
    vbs_path = startup_folder / "屏幕监管系统.vbs"
    if not vbs_path.exists():
        logger.info("开机自启动未安装（未找到启动脚本）")
        return True
    try:
        vbs_path.unlink()
        logger.info("开机自启动已卸载!")
        logger.info(f"已删除: {vbs_path}")
        return True
    except Exception as e:
        logger.error(f"卸载开机自启动失败: {e}")
        return False


class Application:
    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self.scheduler = None
        self.forced_monitor = None
        self.app_observer = None
        self._running = False
        self.mode = "record"
        self._force_mode = False
        self._start_time = None
        self._scheduler_thread = None
        self._data_dir = "data"
        self._log_dir = "logs"
        self.alert_root = None

    def set_alert_root(self, root):
        self.alert_root = root

    def start_background(self, mode: str, force_mode: bool, task_description: str = None) -> bool:
        if self._running:
            return False

        self.mode = mode
        self._force_mode = force_mode
        self._running = True
        self._start_time = datetime.now()

        logger = logging.getLogger(__name__)
        interval = self.config_loader.get_screenshot_interval()

        if self._force_mode:
            if not PSUTIL_AVAILABLE:
                logger.error("psutil 未安装，无法使用强制模式。请运行: pip install psutil")
                self._running = False
                return False
            forbidden_path = Path.cwd() / "forbidden.txt"
            self.forced_monitor = ForcedModeMonitor(
                forbidden_file=str(forbidden_path),
                check_interval=1.0,
                alert_callback=self._on_force_alert
            )
            self.forced_monitor.start()
            logger.info("强制模式已开启")

        # 前台应用使用统计（AppObserver）：应用切换 → 立即补拍；60s 周期任务不变
        tracker_cfg = self.config_loader.config.get("app_tracker", {}) or {}
        if tracker_cfg.get("enabled", True):
            try:
                from src.app_observer import AppObserver
                self.app_observer = AppObserver(
                    data_dir=self._data_dir,
                    poll_seconds=float(tracker_cfg.get("poll_seconds", 1)),
                    idle_threshold_seconds=int(tracker_cfg.get("idle_threshold_minutes", 5)) * 60,
                    record_title=bool(tracker_cfg.get("record_window_title", True)),
                    aliases=tracker_cfg.get("aliases") or {},
                )
                self.app_observer.set_on_switch(self._on_app_switch)
                self.app_observer.start()
                logger.info("前台应用统计已启用")
            except Exception as e:
                logger.warning(f"前台应用统计启动失败: {e}")
                self.app_observer = None

        self._scheduler_thread = threading.Thread(
            target=self._run_scheduler, args=(interval, task_description), daemon=True
        )
        self._scheduler_thread.start()
        logger.info(f"后台监控已启动，截图间隔: {interval} 秒")
        return True

    def _on_force_alert(self, process_name: str):
        if not self.alert_root:
            return

        def show():
            try:
                messagebox.showwarning(
                    "⛔ 软件已被阻止",
                    f"检测到禁止运行的软件：{process_name}\n\n"
                    f"该软件已在 forbidden.txt 黑名单中，\n"
                    f"系统已自动终止该进程。\n\n"
                    f"如需解除禁止，请从 forbidden.txt 中移除对应条目。"
                )
            except Exception:
                pass

        self.alert_root.after(0, show)

    def _on_app_switch(self, info):
        """应用切换 → 立即补一次截图分析（scheduler 内部防抖）。"""
        if self.scheduler is not None:
            try:
                self.scheduler.trigger_switch_capture()
            except Exception:
                pass

    def _run_scheduler(self, interval: int, task_description: str):
        logger = logging.getLogger(__name__)
        try:
            self.scheduler = ScreenMonitorScheduler(
                config=self.config_loader.config,
                data_dir=self._data_dir,
                log_dir=self._log_dir
            )
            if self.app_observer is not None:
                self.scheduler.set_app_observer(self.app_observer)
            if self.mode == "learning" and task_description:
                self.scheduler.set_learning_task(task_description)
            self.scheduler.start()
        except Exception as e:
            logger.error(f"调度器运行异常: {e}")
            import traceback
            traceback.print_exc()

    def stop_all(self):
        if not self._running:
            return
        self._running = False
        if self.app_observer:
            self.app_observer.stop()
        if self.forced_monitor:
            self.forced_monitor.stop()
        if self.scheduler:
            self.scheduler.stop()
        logging.getLogger(__name__).info("所有监控已停止")

    def get_status(self) -> dict:
        scheduler_status = {}
        if self.scheduler:
            scheduler_status = self.scheduler.get_status()

        force_status = {}
        if self.forced_monitor:
            force_status = self.forced_monitor.get_status()

        return {
            "running": self._running,
            "mode": self.mode,
            "force_mode": self._force_mode,
            "app_tracker": self.app_observer is not None,
            "start_time": self._start_time.strftime("%Y-%m-%d %H:%M:%S") if self._start_time else "",
            "uptime_seconds": (datetime.now() - self._start_time).total_seconds() if self._start_time else 0,
            "scheduler": scheduler_status,
            "forced_monitor": force_status
        }


def main():
    args = parse_args()
    setup_logging()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger = logging.getLogger(__name__)

    # 一键启动：直接双击/运行 python main.py（无任何参数）→ 监控 + 悬浮面板一体启动
    if args.command == "start" and len(sys.argv) == 1:
        args.ui = True
        logger.info("一键启动模式：监控 + 悬浮面板")

    if args.install_autostart:
        success = install_autostart()
        return 0 if success else 1

    if args.uninstall_autostart:
        success = uninstall_autostart()
        return 0 if success else 1

    try:
        config_loader = ConfigLoader(args.config)
        logger.info(f"配置文件加载成功: {config_loader.config_path}")
    except FileNotFoundError as e:
        logger.error(f"配置文件加载失败: {e}")
        return 1
    except Exception as e:
        logger.error(f"配置文件解析失败: {e}")
        return 1

    api_config = config_loader.get_active_api_config()
    if not api_config.get("api_key") or not api_config.get("base_url"):
        logger.info("未检测到 API 配置，打开设置界面...")
        try:
            from src.settings_ui import show_settings_dialog
            saved = show_settings_dialog(config_loader)
            if saved:
                config_loader.reload()
                api_config = config_loader.get_active_api_config()
                logger.info("API 配置已加载")
            else:
                logger.info("用户跳过 API 配置，部分功能可能不可用")
        except ImportError as e:
            logger.warning(f"无法打开设置界面: {e}，请手动编辑 config.yaml")

    if args.command == "stop":
        logger.info("stop 命令在当前架构下不支持，请直接关闭监控窗口")
        return 0

    if args.command == "once":
        app = Application(config_loader)
        scheduler = ScreenMonitorScheduler(
            config=config_loader.config,
            data_dir="data",
            log_dir="logs"
        )
        result = scheduler.run_once()
        if scheduler.last_run_success:
            logger.info("任务执行成功")
            return 0
        else:
            logger.error("任务执行失败")
            return 1

    if args.command == "report":
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        scheduler = ScreenMonitorScheduler(
            config=config_loader.config,
            data_dir="data",
            log_dir="logs"
        )
        result = scheduler.generate_report(date_str)
        if result:
            logger.info(f"报告已生成: {result}")
            return 0
        else:
            logger.info(f"没有找到日期 {date_str} 的数据")
            return 1

    if args.command == "ui":
        # 悬浮面板：系统最顶层显示番茄钟 + 当前事件 + 事件历史 + 时间排名
        try:
            from src.overlay import run_overlay
        except ImportError as e:
            logger.error(f"打开悬浮面板失败: {e}")
            logger.error("请先安装 PySide6: pip install PySide6")
            return 1
        logger.info("打开悬浮面板（系统最顶层）…")
        logger.info("提示: 面板实时读取 data/cards.json；关闭窗口即退出面板，不影响后台监控")
        return run_overlay(config_loader.config, data_dir="data")

    if args.command == "start":
        mode = args.mode
        force_mode = args.force_mode

        if mode is None and not args.ui:
            forbidden_path = Path.cwd() / "forbidden.txt"

            while True:
                print()
                print("=" * 50)
                print("  🚀 屏幕监管系统")
                print("=" * 50)
                print()
                autostart_installed = (Path(_get_startup_folder()) / "屏幕监管系统.vbs").exists()
                print(f"  1. 启动记录模式 - 仅记录屏幕活动")
                print(f"  2. 启动学习模式 - 记录 + 检测偏离学习任务")
                print(f"  3. 启动强制模式 - 记录 + 禁止指定软件运行")
                print(f"  4. 管理禁止软件列表")
                print(f"  5. 安装开机自启动（监控+悬浮面板）" + (" [已安装]" if autostart_installed else ""))
                print(f"  6. 卸载开机自启动")
                print(f"  7. 启动监控 + 悬浮面板（一键）")
                print(f"  0. 退出")
                print()

                choice = input("请输入选项 (0-7): ").strip()

                if choice == "0":
                    print("已退出")
                    return 0
                elif choice == "7":
                    mode = "record"
                    force_mode = False
                    args.ui = True
                    break
                elif choice == "1":
                    mode = "record"
                    force_mode = False
                    break
                elif choice == "2":
                    mode = "learning"
                    force_mode = False
                    break
                elif choice == "3":
                    mode = "record"
                    force_mode = True
                    break
                elif choice == "4":
                    print()
                    print("-" * 40)
                    forbidden_items = _load_forbidden_from_file(str(forbidden_path))
                    print("当前禁止列表:")
                    if forbidden_items:
                        for i, item in enumerate(forbidden_items, 1):
                            print(f"  {i}. {item}")
                    else:
                        print("  (空)")
                    print()
                    print("  a. 添加禁止软件")
                    print("  d. 删除禁止软件")
                    print("  q. 返回")
                    sub = input("请输入: ").strip().lower()
                    if sub == "a":
                        print("输入要禁止的进程名（如 notepad.exe），输入空行结束:")
                        while True:
                            new_item = input("  > ").strip()
                            if not new_item:
                                break
                            if new_item not in forbidden_items:
                                forbidden_items.append(new_item)
                                print(f"  已添加: {new_item}")
                        _save_forbidden_to_file(str(forbidden_path), forbidden_items)
                        print("已更新 forbidden.txt")
                    elif sub == "d":
                        while True:
                            try:
                                idx = input("输入要删除的序号 (q 返回): ").strip()
                                if idx.lower() == "q":
                                    break
                                idx = int(idx) - 1
                                if 0 <= idx < len(forbidden_items):
                                    removed = forbidden_items.pop(idx)
                                    _save_forbidden_to_file(str(forbidden_path), forbidden_items)
                                    print(f"已删除: {removed}")
                                else:
                                    print("无效序号")
                            except ValueError:
                                print("请输入有效数字")
                elif choice == "5":
                    print()
                    install_autostart()
                elif choice == "6":
                    print()
                    uninstall_autostart()
                else:
                    print("无效输入，请重新选择")

        if mode is None:
            mode = "record"  # 一键启动（无参数/--ui 未带 --mode）默认记录模式

        logger.info("=" * 50)
        logger.info("🚀 屏幕监管系统启动中")
        logger.info("=" * 50)
        logger.info(f"运行模式: {'学习模式' if mode == 'learning' else '强制模式' if force_mode else '记录模式'}")
        if args.ui:
            logger.info("悬浮面板: 已启用（系统最顶层）")
        if force_mode:
            logger.info(f"强制模式: 已启用")
        logger.info(f"截图间隔: {config_loader.get_screenshot_interval()} 秒")
        logger.info("-" * 50)
        logger.info("按 Ctrl+C 停止监控")
        logger.info("=" * 50)

        app = Application(config_loader)
        global _running_instance
        _running_instance = app

        def signal_handler(sig, frame):
            logger.info("\n正在停止监控...")
            app.stop_all()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        success = app.start_background(mode, force_mode)
        if not success:
            logger.error("❌ 启动监控失败")
            return 1

        if args.ui:
            # 结合模式：监控在后台线程运行，主线程跑悬浮面板（关闭面板即停止监控）
            try:
                from src.overlay import run_overlay
            except ImportError as e:
                logger.error(f"启动悬浮面板失败: {e}")
                logger.error("请先安装 PySide6: pip install PySide6")
                logger.warning("本次仅启动监控（无面板）")
                args.ui = False

        if args.ui:
            logger.info("🖥️ 悬浮面板已启动（监控 + 面板一体运行，关闭面板即停止监控）")
            try:
                return run_overlay(config_loader.config, data_dir="data", app=app)
            finally:
                logger.info("面板已关闭，停止监控…")
                app.stop_all()

        try:
            while True:
                import time
                time.sleep(1)
                status = app.get_status()
                if not status.get("running"):
                    break
        except KeyboardInterrupt:
            logger.info("\n收到停止信号，正在关闭...")
            app.stop_all()

        return 0

    logger.error("未知命令")
    return 1


if __name__ == "__main__":
    sys.exit(main())
