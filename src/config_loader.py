import os
import sys
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


def _get_app_dir() -> Path:
    """获取应用程序所在目录（兼容 PyInstaller 打包后的 exe）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


class ConfigLoader:
    """配置加载器，支持从YAML文件和环境变量加载配置"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = self._find_config_file()
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _find_config_file(self) -> str:
        """查找配置文件"""
        app_dir = _get_app_dir()
        possible_paths = [
            app_dir / "config.yaml",
            Path.cwd() / "config.yaml",
            Path.cwd() / "config" / "config.yaml",
        ]
        for path in possible_paths:
            if path.exists():
                return str(path)
        # 都没找到时，返回 app_dir 下的路径（首次运行会创建）
        return str(app_dir / "config.yaml")

    def _load_config(self) -> None:
        """加载YAML配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """应用环境变量覆盖"""
        env_mappings = {
            "API_BASE_URL": ("api", "base_url"),
            "API_KEY": ("api", "api_key"),
            "API_MODEL": ("api", "model"),
            "SCREENSHOT_INTERVAL": ("screenshot", "interval"),
        }

        for env_var, config_path in env_mappings.items():
            env_value = os.environ.get(env_var)
            if env_value is not None:
                self._set_nested_value(config_path, env_value)

    def _set_nested_value(self, path: tuple, value: str) -> None:
        """设置嵌套配置值"""
        current = self._config
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        final_key = path[-1]
        if final_key in current and isinstance(current[final_key], int):
            current[final_key] = int(value)
        else:
            current[final_key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点分隔的嵌套键"""
        keys = key.split(".")
        current = self._config
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        return current

    def get_api_config(self) -> Dict[str, str]:
        """获取API配置"""
        return self._config.get("api", {})

    def get_screenshot_interval(self) -> int:
        """获取截图间隔时间（秒）"""
        return self._config.get("screenshot", {}).get("interval", 60)

    def get_active_api_config(self) -> Dict[str, str]:
        """获取当前激活平台的API配置（兼容旧接口）"""
        return self.get_api_config()

    def save_api_config(self, base_url: str, api_key: str, model: str) -> None:
        """保存API配置到文件"""
        if "api" not in self._config:
            self._config["api"] = {}
        self._config["api"]["base_url"] = base_url
        self._config["api"]["api_key"] = api_key
        self._config["api"]["model"] = model

        # 确保父目录存在
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)

    @property
    def config(self) -> Dict[str, Any]:
        """返回完整配置字典"""
        return self._config.copy()

    def reload(self) -> None:
        """重新加载配置"""
        self._load_config()


def load_config(config_path: Optional[str] = None) -> ConfigLoader:
    """便捷函数：加载配置并返回ConfigLoader实例"""
    return ConfigLoader(config_path)
