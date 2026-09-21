@echo off
rem ============================================
rem  一键启动：监控 + 悬浮面板（无控制台窗口）
rem  关闭悬浮面板 = 停止监控
rem ============================================
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py
) else (
    start "" python main.py
)
