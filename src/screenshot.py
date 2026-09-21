"""截图模块 - 支持 dxcam 和 mss 回退"""
import base64
import io
import logging
import sys
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

PIL_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    logger.warning("Pillow 库未安装")

DXCAM_AVAILABLE = False
dxcam = None

logger.warning("dxcam 与 Python 3.14 不兼容，已禁用，使用 mss 作为替代")

MSS_AVAILABLE = False
try:
    import mss
    MSS_AVAILABLE = True
    logger.info("mss 库加载成功")
except ImportError:
    logger.warning("mss 库未安装")


class ScreenCapture:
    def __init__(self):
        self.camera = None
        self.is_capturing = False

    def init_dxcam(self):
        if not DXCAM_AVAILABLE or dxcam is None:
            return False
        try:
            self.camera = dxcam.create()
            logger.info("dxcam 屏幕捕获初始化成功")
            return True
        except Exception as e:
            logger.error(f"dxcam 初始化失败: {e}")
            return False

    def capture_dxcam(self):
        if self.camera is None:
            if not self.init_dxcam():
                return None
        try:
            frame = self.camera.grab()
            return frame
        except Exception as e:
            logger.error(f"dxcam 截图失败: {e}")
            self.camera = None
            return None

    def capture_mss(self):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)
                if PIL_AVAILABLE:
                    img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                    return img
                else:
                    return screenshot
        except Exception as e:
            logger.error(f"mss 截图失败: {e}")
            return None

    def capture(self):
        frame = self.capture_dxcam()
        if frame is None:
            frame = self.capture_mss()
        return frame

    def release(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        logger.info("屏幕捕获已释放")


def numpy_to_base64(frame) -> str:
    if frame is None:
        return ""

    if PIL_AVAILABLE and not isinstance(frame, bytes):
        img = Image.fromarray(frame) if hasattr(frame, 'shape') else frame
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    else:
        if isinstance(frame, bytes):
            return base64.b64encode(frame).decode("utf-8")
        elif hasattr(frame, 'rgb'):
            return base64.b64encode(frame.rgb).decode("utf-8")
        return ""


def capture_screen() -> str:
    cap = ScreenCapture()
    try:
        frame = cap.capture()
        if frame is not None:
            return numpy_to_base64(frame)
        return None
    except Exception as e:
        logger.error(f"截图失败: {e}")
        return None
    finally:
        cap.release()


def save_screenshot(frame, output_path: str = None) -> str:
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"screenshots/screen_{timestamp}.jpg"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if PIL_AVAILABLE and not isinstance(frame, bytes):
        img = Image.fromarray(frame) if hasattr(frame, 'shape') else frame
        img.save(output_path, "JPEG", quality=85)
    else:
        if isinstance(frame, bytes):
            with open(output_path, "wb") as f:
                f.write(frame)
        elif hasattr(frame, 'rgb'):
            img = Image.frombytes("RGB", frame.size, frame.rgb)
            img.save(output_path, "JPEG", quality=85)
        else:
            with open(output_path, "wb") as f:
                f.write(frame.tobytes() if hasattr(frame, 'tobytes') else frame)

    logger.info(f"截图已保存: {output_path}")
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("测试截图功能...")
    result = capture_screen()
    if result:
        print(f"截图成功，base64 长度: {len(result)}")
    else:
        print("截图失败")
