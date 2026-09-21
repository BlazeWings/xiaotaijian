# 小太监

一个基于 AI 视觉模型的屏幕截图监管系统，支持定时截图并通过 AI API 进行内容分析。

## 功能特性

- 定时自动截图 + AI 内容分析
- 支持任意 OpenAI 兼容 API（智谱、硅基流动、OpenAI、DeepSeek 等）
- 首次启动引导配置 API（Base URL / API Key / 模型）
- 悬浮面板：番茄钟 + 当前事件 + 时间排名
- 前台应用使用统计
- 强制模式：禁止指定软件运行
- 每日活动报告

## 快速开始

### 方式一：下载 exe（推荐）

1. 从 [Releases](../../releases) 下载最新版本
2. 解压后双击 `screen_monitor.exe`
3. 首次启动会弹出 API 设置界面，填入你的 API 信息即可

### 方式二：源码运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动（首次会弹出设置界面）
python main.py
```

## API 配置

首次启动时会自动弹出设置界面，也可通过编辑 `config.yaml` 手动配置：

```yaml
api:
  base_url: "https://api.example.com/v1/chat/completions"
  api_key: "sk-your-api-key"
  model: "your-model-name"
```

### 推荐服务商

| 服务商 | 地址 | 推荐模型 | 说明 |
|--------|------|----------|------|
| 智谱 AI | https://open.bigmodel.cn | glm-4v-flash | 免费额度 |
| 硅基流动 | https://siliconflow.cn | THUDM/GLM-4.1V-9B-Thinking | 免费额度 |
| OpenAI | https://platform.openai.com | gpt-4o | 付费 |
| DeepSeek | https://platform.deepseek.com | deepseek-chat | 付费 |

任何兼容 OpenAI API 格式的服务均可使用。

## 使用方式

```bash
python main.py                        # 一键启动：监控 + 悬浮面板
python main.py start                  # 启动持续监控
python main.py start --ui             # 监控 + 悬浮面板
python main.py once                   # 执行一次截图分析
python main.py report                 # 生成今日报告
python main.py ui                     # 仅打开悬浮面板
```

## 悬浮面板功能

- 番茄钟 / 倒计时 / 秒表
- 当前事件实时显示
- 时间排名（今日 / 本周 / 全部）
- 强制模式管理（禁止指定软件）
- 淡化模式、最小化模式

## 项目结构

```
screen_monitor/
├── main.py                 # 主入口
├── config.yaml             # 配置文件
├── requirements.txt        # Python 依赖
├── screen_monitor.spec     # PyInstaller 打包配置
├── 启动面板.bat            # 一键启动脚本
├── forbidden.txt           # 强制模式黑名单
└── src/
    ├── ai_api.py           # AI API 调用
    ├── settings_ui.py      # API 设置界面
    ├── config_loader.py    # 配置加载
    ├── scheduler.py        # 定时调度
    ├── screenshot.py       # 截图模块
    ├── card_generator.py   # 卡片生成
    ├── report_generator.py # 报告生成
    ├── activity_stats.py   # 活动统计
    ├── app_observer.py     # 前台应用监控
    ├── forced_mode.py      # 强制模式
    └── overlay.py          # 悬浮面板 UI
```

## 打包为 exe

```bash
pip install pyinstaller
pyinstaller screen_monitor.spec
```

输出文件位于 `dist/screen_monitor.exe`。

## 许可证

MIT License
