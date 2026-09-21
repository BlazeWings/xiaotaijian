"""只截面板区域 - 等待面板完全渲染后再截"""
import time, ctypes, ctypes.wintypes, mss
from PIL import Image
from pathlib import Path
import sys, os

SAVE_DIR = Path(r"D:\临时文档\作品与软件\小太监-开源版\docs\images")
SAVE_DIR.mkdir(parents=True, exist_ok=True)
APP_DIR = Path(r"D:\临时文档\作品与软件\小太监-开源版")

os.chdir(str(APP_DIR))
sys.path.insert(0, str(APP_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from src.config_loader import ConfigLoader
from src.overlay import OverlayWindow

app = QApplication(sys.argv)
config = ConfigLoader()
window = OverlayWindow(config.config, data_dir=str(APP_DIR / "data"))
window.show()

# 强制渲染多轮
for _ in range(10):
    app.processEvents()
    time.sleep(0.1)

print(f"Panel window ID: {int(window.winId())}")
print(f"Panel geometry: {window.x()},{window.y()} {window.width()}x{window.height()}")

time.sleep(3)  # 等3秒让面板完全稳定

# 用 Win32 直接拿这个窗口的精确位置
user32 = ctypes.windll.user32
hwnd = int(window.winId())
rect = ctypes.wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
hx, hy, hw, hh = rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
print(f"Win32 rect: ({hx},{hy}) {hw}x{hh}")

time.sleep(1)

# 截面板
pad = 2
region = {"left": max(0, hx-pad), "top": max(0, hy-pad), "width": hw+pad*2, "height": hh+pad*2}
with mss.mss() as sct:
    shot = sct.grab(region)
    img = Image.frombytes("RGB", shot.size, shot.rgb)

    # 保存完整面板
    img.save(str(SAVE_DIR / "panel_full.png"), "PNG")
    print(f"Saved panel_full.png ({img.width}x{img.height})")

    # 截最小化模式
    img.crop((0, 0, img.width, min(420, img.height))).save(str(SAVE_DIR / "panel_mini.png"), "PNG")
    print("Saved panel_mini.png")

app.quit()
print("Done!")
