"""API 设置界面 - 首次启动时引导用户配置 Base URL、API Key 和模型"""
import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

BG = "#f5f0e6"
PANEL = "#ffffff"
BORDER = "#000000"
TEXT = "#111111"
MUTED = "#5c5c5c"
ACCENT = "#ff6b6b"
ACCENT_HOVER = "#ff8787"
ACCENT_DARK = "#e03131"
GREEN = "#2f9e44"
YELLOW = "#ffd43b"

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
QLineEdit {{
    background: {PANEL};
    color: {TEXT};
    border: 2px solid {BORDER};
    border-radius: 0px;
    padding: 6px 10px;
    font-size: 12px;
}}
QLineEdit:focus {{
    border: 2px solid {ACCENT};
}}
QPushButton {{
    background: {PANEL};
    color: {TEXT};
    border: 2px solid {BORDER};
    border-radius: 0px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 700;
}}
QPushButton:hover {{ background: {YELLOW}; }}
QPushButton:pressed {{ background: #ffe066; }}
QPushButton#accent {{
    background: {ACCENT};
    color: #ffffff;
    font-weight: 800;
}}
QPushButton#accent:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#accent:pressed {{ background: {ACCENT_DARK}; }}
QPushButton#ghost {{
    background: transparent;
    color: {MUTED};
    border: 2px solid transparent;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#ghost:hover {{ background: {YELLOW}; border: 2px solid {BORDER}; color: {TEXT}; }}
QTextEdit {{
    background: {PANEL};
    color: {TEXT};
    border: 2px solid {BORDER};
    border-radius: 0px;
    padding: 6px 10px;
    font-size: 11px;
}}
"""


class SettingsDialog(QDialog):
    """API 设置对话框"""

    def __init__(self, config_loader, parent=None):
        super().__init__(parent)
        self.config_loader = config_loader
        self._saved = False

        self.setWindowTitle("屏幕监管系统 - API 设置")
        self.setFixedSize(520, 520)
        self.setStyleSheet(QSS)
        self.setFont(QFont("Microsoft YaHei UI", 10))

        self._build_ui()
        self._load_current_config()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("⚙ API 设置")
        title.setStyleSheet("font-size:18px; font-weight:800;")
        root.addWidget(title)

        desc = QLabel("首次使用请配置 AI API。支持任何 OpenAI 兼容接口。")
        desc.setStyleSheet(f"font-size:12px; color:{MUTED};")
        desc.setWordWrap(True)
        root.addWidget(desc)

        card = QFrame()
        card.setObjectName("panel")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 12)
        card_lay.setSpacing(8)

        # Base URL
        card_lay.addWidget(QLabel("Base URL"))
        self._base_url_input = QLineEdit()
        self._base_url_input.setPlaceholderText("https://api.example.com/v1/chat/completions")
        card_lay.addWidget(self._base_url_input)

        # API Key
        card_lay.addWidget(QLabel("API Key"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("sk-...")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        card_lay.addWidget(self._api_key_input)

        # Model
        card_lay.addWidget(QLabel("模型名称"))
        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("gpt-4o / glm-4v-flash / Qwen/Qwen2.5-VL-72B-Instruct 等")
        card_lay.addWidget(self._model_input)

        root.addWidget(card)

        # 推荐服务商
        info_card = QFrame()
        info_card.setObjectName("panel")
        info_lay = QVBoxLayout(info_card)
        info_lay.setContentsMargins(14, 10, 14, 10)
        info_lay.setSpacing(4)

        info_title = QLabel("💡 推荐服务商")
        info_title.setStyleSheet("font-size:13px; font-weight:800;")
        info_lay.addWidget(info_title)

        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(120)
        info_text.setPlainText(
            "• 智谱 AI (https://open.bigmodel.cn) — glm-4v-flash 免费\n"
            "• 硅基流动 (https://siliconflow.cn) — GLM-4.1V-9B-Thinking 免费\n"
            "• OpenAI / DeepSeek / 任意 OpenAI 兼容接口\n\n"
            "填入对应服务商的 API 地址、密钥和模型名即可。"
        )
        info_lay.addWidget(info_text)

        root.addWidget(info_card)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._skip_btn = QPushButton("跳过")
        self._skip_btn.setObjectName("ghost")
        self._skip_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._skip_btn)
        self._save_btn = QPushButton("保存并启动")
        self._save_btn.setObjectName("accent")
        self._save_btn.clicked.connect(self._save_and_accept)
        btn_row.addWidget(self._save_btn)
        root.addLayout(btn_row)

    def _load_current_config(self):
        api = self.config_loader.get_api_config()
        self._base_url_input.setText(api.get("base_url", ""))
        self._api_key_input.setText(api.get("api_key", ""))
        self._model_input.setText(api.get("model", ""))

    def _save_and_accept(self):
        base_url = self._base_url_input.text().strip()
        api_key = self._api_key_input.text().strip()
        model = self._model_input.text().strip()

        if not base_url or not api_key:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请填写 Base URL 和 API Key")
            return

        self.config_loader.save_api_config(base_url, api_key, model)
        self._saved = True
        logger.info("API 配置已保存")
        self.accept()

    @property
    def saved(self) -> bool:
        return self._saved


def show_settings_dialog(config_loader) -> bool:
    """显示设置对话框，返回是否保存了配置"""
    import sys
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    dialog = SettingsDialog(config_loader)
    dialog.exec()
    return dialog.saved
