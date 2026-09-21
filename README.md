# 🏯 小太监

> *一屏一世界，一念一浮生。*
>
> 愿它如一位忠诚的小太监，替你掌管时间、记录行止、提醒专注。

![界面预览](https://raw.githubusercontent.com/BlazeWings/xiaotaijian/main/docs/images/screenshot_1.png)

**小太监** 是一位安静的屏幕侍从。它默默注视你的屏幕，用 AI 之眼解读你正在做什么，化为一张张时光卡片；它在屏幕一角悬挂一面"照妖镜"，让你随时看清自己的时间去了哪里。

---

## ✨ 功能特色

### 🖼️ AI 慧眼识屏

每隔一段时间，小太监会悄悄截取一屏，请 AI 视觉模型端详一番——你在写代码？刷视频？摸鱼聊天？它会将观察化为一张卡片，记录时间、活动与类别，汇成你一天的"时光画卷"。

支持任何 OpenAI 兼容接口，智谱、硅基流动、OpenAI、DeepSeek……皆可为它所用。

### ⏳ 三合一计时器

悬浮面板顶部，藏着一个 Catime 式的三面计时器：

- **🍅 番茄钟** — 专注与休息的韵律，25/5/15 分钟如呼吸般自然轮转；亦可自定义节奏，如 `[25, 5, 25, 15]`，让时间随你的意志流转
- **⏳ 倒计时** — 点击数字，随心设定：`25` 是25分钟，`90s` 是90秒，`1h 30m` 是一个半小时，`130 20` 是130分20秒……到点轻响，化作正计时继续流淌
- **⏱ 秒表** — 纯粹的正计时，丈量每一刻

更有 **🔗 到时动作**：为任何计时阶段设定一个网址，时间归零时自动在浏览器打开——是时候站起来走走了。

### 🎯 当前任务提醒

在面板上写下"我现在在干什么"，它便化为醒目的红字，时刻提醒你勿忘初心。点击即可修改，留空则散去。它会记住你的设定，重启后依然在此守候。

### 👻 淡化模式（透明模式）

嫌它碍眼？点一下 👻，面板便化作半透明的幽灵，隐入背景，你可透过它看到后面的内容。鼠标轻轻靠近，它又恢复实体；移开，再度淡去。若即若离，恰到好处。

### 🗕 最小化视图

双击标题栏或点 ─ 按钮，面板收缩为精简模式：只保留计时器、当前任务和当前事件。像一枚小巧的书签，静静贴在屏幕角落。

### 📌 永远置顶

面板默认悬浮于所有窗口之上，每秒以 Win32 `SetWindowPos` 重新宣示主权，不被其他置顶窗口夺去顶层。📌 按钮可随时切换是否置顶。

> *注：独占全屏游戏会完全接管画面，需将游戏改为无边框窗口化模式，小太监才能浮于其上。*

### 🏆 时间排名

相似的活动自动归类，按累计时长排成一榜。今日花了多少时间学习？本周摸鱼几许？全部历史又是怎样的光景？排名实时滚动，当前正在进行的活动会以 ▶ 绿色箭头标记，一眼便知。

### 📱 前台应用统计

小太监每秒轮询前台窗口，像 Tai 一样精确记录每个应用的使用时长。切换应用时立即补拍一次截图分析，新应用一秒内即有语义卡片。它还会聪明地学习应用别名——`WeChat.exe` 变成"微信"，`Code.exe` 变成"VS Code"。

无操作超过五分钟？它会默默等待你归来，不打扰，不灌水。

### ⛔ 强制模式（自律之锁）

此乃小太监最严厉的一面。开启后，黑名单中的软件一旦运行，即被自动终止——游戏、社交软件，统统拦下。

- **热启停**：面板内一键开关，无需重启
- **黑名单管理**：展开卡片即可添加、删除禁止的软件，实时生效
- **关闭确认**：连续三次弹窗确认，防你一冲动关掉自控
- **定时重开**：关闭后可设定"30分钟后自动重新开启"，给自己一个缓冲，却不给自己逃走的机会

### 📊 每日报告

每日活动自动生成报告：各类别占比、活动时间线、相似事件合并……你的每一天，都有迹可循。

### 🚀 开机自启动

一条命令，小太监便在开机时自动苏醒，守护你的屏幕：

```bash
python main.py --install-autostart
```

---

## 🖼️ 界面一览

| 悬浮面板 | 运行状态 |
|---------|---------|
| ![面板](https://raw.githubusercontent.com/BlazeWings/xiaotaijian/main/docs/images/screenshot_2.png) | ![运行](https://raw.githubusercontent.com/BlazeWings/xiaotaijian/main/docs/images/screenshot_3.png) |

界面采用 **新粗野主义（Neobrutalism）** 风格：米色底 + 黑色粗描边 + 硬阴影 + 平涂亮色，干净利落，不媚不俗。

---

## 🚀 快速开始

### 方式一：下载 exe（推荐）

1. 前往 [Releases](../../releases) 下载最新版本
2. 将 `screen_monitor.exe` 放入任意文件夹
3. 双击运行——首次启动会弹出 API 设置界面，填入你的 API 信息即可

配置文件 `config.yaml` 会自动生成在 exe 同目录。

### 方式二：源码运行

```bash
pip install -r requirements.txt
python main.py
```

---

## ⚙️ API 配置

首次启动自动弹出设置界面，也可手动编辑 `config.yaml`：

```yaml
api:
  base_url: "https://open.bigmodel.cn/api/paas/v4/chat/completions"
  api_key: "your-api-key"
  model: "glm-4v-flash"
```

### 推荐服务商

| 服务商 | Base URL | 推荐模型 | 费用 |
|--------|----------|----------|------|
| [智谱 AI](https://open.bigmodel.cn) | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `glm-4v-flash` | 有免费额度 |
| [硅基流动](https://siliconflow.cn) | `https://api.siliconflow.cn/v1/chat/completions` | `THUDM/GLM-4.1V-9B-Thinking` | 有免费额度 |
| [OpenAI](https://platform.openai.com) | `https://api.openai.com/v1/chat/completions` | `gpt-4o` | 付费 |
| [DeepSeek](https://platform.deepseek.com) | `https://api.deepseek.com/v1/chat/completions` | `deepseek-chat` | 付费 |

> 任何兼容 OpenAI Chat Completions 格式的服务均可使用。

---

## 📖 使用方式

```bash
python main.py                        # 一键启动：监控 + 悬浮面板
python main.py start                  # 启动持续监控（交互菜单）
python main.py start --ui             # 监控 + 悬浮面板一体
python main.py start --mode record    # 直接以记录模式启动
python main.py start --mode learning  # 学习模式（检测偏离任务）
python main.py start --force-mode     # 强制模式（禁止黑名单软件）
python main.py once                   # 执行一次截图分析
python main.py report                 # 生成今日报告
python main.py ui                     # 仅打开悬浮面板
python main.py --install-autostart    # 安装开机自启动
python main.py --uninstall-autostart  # 卸载开机自启动
```

---

## 📁 项目结构

```
xiaotaijian/
├── main.py                 # 主入口
├── config.yaml             # 配置文件（首次运行自动生成）
├── requirements.txt        # Python 依赖
├── screen_monitor.spec     # PyInstaller 打包配置
├── 启动面板.bat            # 一键启动脚本
├── forbidden.txt           # 强制模式黑名单
├── docs/images/            # 截图
└── src/
    ├── ai_api.py           # AI API 调用（OpenAI 兼容）
    ├── settings_ui.py      # API 设置界面
    ├── config_loader.py    # 配置加载
    ├── scheduler.py        # 定时调度
    ├── screenshot.py       # 截图模块
    ├── card_generator.py   # 卡片生成
    ├── report_generator.py # 报告生成
    ├── activity_stats.py   # 活动统计与排名
    ├── app_observer.py     # 前台应用监控
    ├── forced_mode.py      # 强制模式
    └── overlay.py          # 悬浮面板 UI（PySide6）
```

---

## 🔨 打包为 exe

```bash
pip install pyinstaller
pyinstaller screen_monitor.spec
```

输出位于 `dist/screen_monitor.exe`。

---

## ❓ 常见问题

**Q: exe 运行后找不到配置文件？**
A: 首次运行会在 exe 同目录自动生成 `config.yaml`，无需手动创建。

**Q: 如何更换 AI 服务商？**
A: 编辑 `config.yaml` 中的 `api` 段，或删除配置文件后重新启动，弹出设置界面即可。

**Q: 面板被游戏挡住了？**
A: 独占全屏游戏会接管画面，请将游戏改为"无边框窗口化"模式。

**Q: 数据存在哪里？**
A: 所有数据（截图、卡片、报告）都保存在 exe 同目录的 `data/` 文件夹中，卸载时直接删除整个文件夹即可。

---

## 📜 许可证

MIT License
