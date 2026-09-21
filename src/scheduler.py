"""定时任务模块"""
import logging
import sys
import threading
import time
import base64
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from . import screenshot
from . import ai_api
from . import card_generator
from . import report_generator


class ScreenMonitorScheduler:
    def __init__(self, config: dict, data_dir: str, log_dir: str):
        self.config = config
        self.data_dir = Path(data_dir)
        self.log_dir = Path(log_dir)
        self.interval = config.get("screenshot", {}).get("interval", 300)

        self._timer = None
        self._running = False
        self._lock = threading.Lock()

        self._task_count = 0
        self._last_run_time = None
        self._last_run_success = False
        self._last_report_date = None

        self.learning_mode_state = {
            "enabled": False,
            "task": "",
            "start_time": None,
            "check_enabled": True
        }

        # 前台应用统计（AppObserver）：提供 app 上下文、切换触发、类别学习
        self._app_observer = None
        self._task_lock = threading.Lock()
        self._last_task_end_mono = 0.0
        self._switch_debounce = float(
            config.get("app_tracker", {}).get("switch_debounce_seconds", 10)
        )
        # 切换补拍 pending：被防抖/锁挡下的请求不丢弃，择机补一次
        self._switch_pending = False
        self._pending_timer = None

        self._ensure_directories()

        self.cap = screenshot.ScreenCapture()
        try:
            self.cap.init()
        except Exception as e:
            logger.error(f"屏幕捕获初始化失败: {e}")

    def _ensure_directories(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "cards").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "report").mkdir(parents=True, exist_ok=True)
        logger.info(f"数据目录: {self.data_dir}")
        logger.info(f"日志目录: {self.log_dir}")

    def _capture_screenshot(self) -> dict:
        try:
            frame = self.cap.capture()
            if frame is None:
                return {"success": False, "error": "截图返回为空"}

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_dir = self.data_dir / "screenshots"
            image_path = screenshot_dir / f"screen_{timestamp}.jpg"

            screenshot.save_screenshot(frame, str(image_path))

            logger.info(f"截图成功: {image_path}")

            image_base64 = screenshot.numpy_to_base64(frame)

            return {
                "success": True,
                "image_base64": image_base64,
                "image_path": str(image_path)
            }

        except Exception as e:
            error_msg = f"截图过程出错: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

    def _analyze_image(self, image_base64: str, app_context: dict = None) -> dict:
        try:
            return ai_api.analyze_screen(image_base64, self.config, app_context=app_context)
        except Exception as e:
            error_msg = f"图像分析出错: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

    # ---------- 前台应用统计（AppObserver）接入 ----------
    def set_app_observer(self, observer):
        self._app_observer = observer

    def _get_app_context(self):
        """取当前前台应用上下文；未启用/离开时返回相应状态。"""
        if self._app_observer is None:
            return None
        try:
            return self._app_observer.get_current()
        except Exception:
            return None

    def trigger_switch_capture(self):
        """应用切换时请求一次额外截图分析（请求不丢弃）。

        能立即执行就直接补拍；若撞上任务进行中或防抖期，记入 pending，
        由任务结束/防抖到期后补——保证任何切换最终都有对应卡片。
        快速连续横跳会被合并为一次补拍（取最新应用）。
        """
        if not self._running:
            return
        with self._lock:
            self._switch_pending = True
        self._try_run_pending_switch()

    def _try_run_pending_switch(self):
        with self._lock:
            if not self._switch_pending or not self._running:
                return
            if self._task_lock.locked():
                return  # 任务结束时 _run_task 会再次调用本方法
            wait = self._switch_debounce - (time.monotonic() - self._last_task_end_mono)
            if wait > 0:
                # 防抖期内：到期后重试（同时只保留一个重试定时器）
                if self._pending_timer is None:
                    self._pending_timer = threading.Timer(wait + 0.1, self._on_pending_timer)
                    self._pending_timer.daemon = True
                    self._pending_timer.start()
                return
            self._switch_pending = False
        threading.Thread(target=self._run_task, kwargs={"force": True, "schedule_next": False},
                         daemon=True, name="SwitchCapture").start()

    def _on_pending_timer(self):
        with self._lock:
            self._pending_timer = None
        self._try_run_pending_switch()

    def _generate_report_if_needed(self):
        today_str = datetime.now().strftime("%Y-%m-%d")

        try:
            result = report_generator.generate_daily_report(today_str, str(self.data_dir))
            if result:
                self._last_report_date = today_str
                logger.info(f"日报生成成功: {result}")
            else:
                logger.info(f"今日暂无数据，跳过报告生成")
        except Exception as e:
            logger.error(f"生成日报失败: {e}")

    def _run_task(self, force=False, schedule_next=True):
        """执行一次截图分析任务。

        schedule_next: 是否为周期链安排下一次运行。切换触发的补拍传 False，
        避免在周期 Timer 链之外额外套出新的 Timer 链。
        """
        if not force:
            with self._lock:
                if not self._running:
                    logger.info("调度器未运行，使用 run_once 模式")
                else:
                    logger.info("调度器运行中")

        with self._task_lock:
            self._run_task_body()

        self._last_task_end_mono = time.monotonic()
        if schedule_next:
            self._schedule_next_run()
        # 有 pending 的切换补拍请求时立即补一次
        self._try_run_pending_switch()

    def _run_task_body(self):
        task_start_time = datetime.now()
        self._task_count += 1
        task_id = self._task_count

        logger.info(f"========== 开始执行任务 #{task_id} ==========")

        result = {
            "task_id": task_id,
            "start_time": task_start_time.isoformat(),
            "success": False,
            "error": None,
            "description": "",
            "category": ""
        }

        try:
            # 前台应用上下文（AppObserver）；离开状态直接跳过本次分析，不灌水
            app_ctx = self._get_app_context()
            if app_ctx and app_ctx.get("is_idle"):
                logger.info("用户离开中，跳过本次截图分析")
                result["success"] = True
                result["description"] = "（离开中，跳过）"
                self._last_run_success = True
                return

            screenshot_result = self._capture_screenshot()
            if not screenshot_result.get("success"):
                raise Exception(f"截图失败: {screenshot_result.get('error')}")

            image_base64 = screenshot_result["image_base64"]
            image_path = screenshot_result.get("image_path")
            logger.info(f"截图成功: {image_path}")

            analysis_result = self._analyze_image(image_base64, app_context=app_ctx)
            if not analysis_result.get("success"):
                raise Exception(f"分析失败: {analysis_result.get('error')}")

            description = analysis_result.get("description", "")
            category = analysis_result.get("category", "其他")
            logger.info(f"分析结果: {description} (类别: {category})")

            if self.learning_mode_state["enabled"] and self.learning_mode_state["check_enabled"]:
                logger.info(f"学习模式已启用，开始判断相关性...")
                logger.info(f"任务: {self.learning_mode_state['task']}")
                logger.info(f"当前活动: {description}")
                relevance_result = ai_api.check_activity_relevance(
                    self.learning_mode_state["task"],
                    description,
                    self.config
                )
                logger.info(f"相关性判断结果: {relevance_result}")
                if relevance_result.get("success") and not relevance_result.get("is_relevant", True):
                    logger.warning(f"⚠️ 检测到不相关活动，准备弹窗提醒...")
                    self.show_relevance_alert(description)

            card = card_generator.generate_card(analysis_result, app_context=app_ctx)
            card_generator.save_card(card, str(self.data_dir))
            logger.info(f"卡片已保存")

            # 用卡片类别反哺「应用 → 类别」映射（多数决）
            if app_ctx and app_ctx.get("app") and self._app_observer is not None:
                try:
                    self._app_observer.update_app_category(app_ctx["app"], card.get("category", "其他"))
                except Exception:
                    pass

            timestamp_str = task_start_time.strftime("%Y%m%d_%H%M%S")
            date_folder = f"{task_start_time.month}.{task_start_time.day}"
            date_card_dir = self.data_dir / "cards" / date_folder
            date_card_dir.mkdir(parents=True, exist_ok=True)
            card_path = date_card_dir / f"card_{timestamp_str}.png"
            card_generator.create_card_image(image_path, card, str(card_path))

            result["success"] = True
            result["description"] = description
            result["category"] = category
            result["card_path"] = str(card_path)
            result["image_path"] = image_path

            self._last_run_success = True

            self._generate_report_if_needed()

        except Exception as e:
            error_msg = str(e)
            logger.error(f"任务 #{task_id} 执行失败: {error_msg}")
            result["error"] = error_msg
            self._last_run_success = False

        task_end_time = datetime.now()
        duration = (task_end_time - task_start_time).total_seconds()
        result["end_time"] = task_end_time.isoformat()
        result["duration_seconds"] = duration

        self._last_run_time = task_end_time

        logger.info(f"========== 任务 #{task_id} 结束 (耗时: {duration:.2f}s) ==========")

    def _schedule_next_run(self):
        with self._lock:
            if not self._running:
                logger.info("调度器已停止，不再安排下次任务")
                return

            self._timer = threading.Timer(self.interval, self._run_task)
            self._timer.daemon = True
            self._timer.start()
            next_run_time = datetime.now().timestamp() + self.interval
            next_run_str = datetime.fromtimestamp(next_run_time).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"下次任务将在 {self.interval} 秒后执行 ({next_run_str})")

    def start(self):
        with self._lock:
            if self._running:
                logger.warning("调度器已在运行中")
                return

            self._running = True
            self._last_report_date = datetime.now().strftime("%Y-%m-%d")
            logger.info(f"启动调度器，间隔: {self.interval} 秒")

        self._run_task()

    def stop(self):
        with self._lock:
            if not self._running:
                logger.warning("调度器未在运行")
                return

            self._running = False

            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

            if self._pending_timer is not None:
                self._pending_timer.cancel()
                self._pending_timer = None
            self._switch_pending = False

            self.cap.release()
            logger.info("调度器已停止")

    def run_once(self):
        logger.info("手动执行一次任务")
        self._run_task(force=True)
        self._generate_report_if_needed()
        return {
            "success": self._last_run_success,
            "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None
        }

    def generate_report(self, date_str: str = None):
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        return report_generator.generate_daily_report(date_str, str(self.data_dir))

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def task_count(self) -> int:
        return self._task_count

    @property
    def last_run_time(self):
        return self._last_run_time

    @property
    def last_run_success(self) -> bool:
        return self._last_run_success

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "interval": self.interval,
            "task_count": self._task_count,
            "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
            "last_run_success": self._last_run_success
        }

    def set_learning_task(self, task: str):
        self.learning_mode_state["task"] = task
        self.learning_mode_state["enabled"] = True
        self.learning_mode_state["start_time"] = datetime.now()
        logger.info(f"学习模式已开启，任务: {task}")

    def get_learning_status(self) -> dict:
        return self.learning_mode_state

    def show_relevance_alert(self, current_activity: str):
        import ctypes
        import subprocess

        def show_alert():
            try:
                logger.warning("=" * 50)
                logger.warning("⚠️ 专注提醒")
                logger.warning(f"学习任务: {self.learning_mode_state['task']}")
                logger.warning(f"当前活动: {current_activity}")
                logger.warning("当前活动可能与学习任务不相关，请保持专注！")
                logger.warning("=" * 50)
            except Exception as e:
                logger.error(f"弹窗显示失败: {e}")
                try:
                    ctypes.windll.user32.MessageBoxW(
                        0,
                        f"学习任务: {self.learning_mode_state['task']}\n\n"
                        f"当前活动: {current_activity}\n\n"
                        f"当前活动可能与学习任务不相关，请保持专注！",
                        "⚠️ 专注提醒",
                        0x40 | 0x1000
                    )
                except Exception as e2:
                    logger.error(f"Windows 消息框也失败: {e2}")

        alert_thread = threading.Thread(target=show_alert, daemon=False)
        alert_thread.start()
