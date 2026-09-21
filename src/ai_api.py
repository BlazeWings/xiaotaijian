"""AI API 调用模块 - 支持自定义 OpenAI 兼容接口"""
import logging
import requests
import json

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60

ANALYSIS_PROMPT = """请分析这张屏幕截图，描述用户当前正在做什么。

请按以下JSON格式回答，只返回JSON，不要有多余的文本：
{
    "activity": "简要描述用户当前的操作（一句话）",
    "category": "从以下类别中选择一个最合适的：工作/学习、娱乐休闲、通讯交流、信息检索、系统操作、其他"
}"""


def build_analysis_prompt(app_context: dict = None) -> str:
    """拼接分析提示词；有前台应用上下文时加一行锚点信息，提高描述准确性与措辞稳定性。"""
    if not app_context:
        return ANALYSIS_PROMPT
    app = app_context.get("app") or ""
    if not app:
        return ANALYSIS_PROMPT
    title = (app_context.get("title") or "").strip()
    duration = app_context.get("duration")
    parts = [f"当前前台应用：{app}"]
    if title:
        parts.append(f"窗口标题：\"{title[:80]}\"")
    if isinstance(duration, (int, float)) and duration > 0:
        m = int(duration // 60)
        parts.append(f"已持续 {m} 分钟" if m > 0 else f"已持续 {int(duration)} 秒")
    return "，".join(parts) + "。\n\n" + ANALYSIS_PROMPT


def call_api(image_base64: str, api_key: str, base_url: str, model: str, prompt: str = ANALYSIS_PROMPT) -> dict:
    """调用 OpenAI 兼容的视觉分析 API"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 500
    }

    try:
        logger.info(f"调用 API: {base_url}")
        response = requests.post(
            base_url,
            headers=headers,
            json=payload,
            timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()

        result = response.json()
        logger.info(f"API 响应: {result}")

        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            logger.info("API 调用成功")
            return {
                "success": True,
                "content": content,
                "model": model,
                "platform": "custom"
            }
        else:
            error_msg = result.get("error", {}).get("message", str(result))
            logger.error(f"API 返回异常: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "platform": "custom"
            }

    except requests.exceptions.Timeout:
        error_msg = f"API 请求超时 ({DEFAULT_TIMEOUT}s)"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "platform": "custom"}
    except requests.exceptions.RequestException as e:
        error_msg = f"API 请求失败: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "platform": "custom"}
    except Exception as e:
        error_msg = f"API 处理异常: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "platform": "custom"}


def parse_analysis_result(content: str) -> dict:
    result = {
        "description": "",
        "category": "其他"
    }

    if not content:
        return result

    try:
        if content.strip().startswith("{"):
            data = json.loads(content)
            result["description"] = data.get("activity", "")
            result["category"] = data.get("category", "其他")
            return result
    except json.JSONDecodeError:
        pass

    lines = content.strip().split("\n")
    for line in lines:
        line = line.strip()
        if "活动描述" in line or "描述" in line or "activity" in line.lower():
            parts = line.split("：", 1) if "：" in line else line.split(":", 1)
            if len(parts) > 1:
                result["description"] = parts[1].strip().strip('",')
        elif "活动类别" in line or "类别" in line or "category" in line.lower():
            parts = line.split("：", 1) if "：" in line else line.split(":", 1)
            if len(parts) > 1:
                category = parts[1].strip().strip('",')
                valid_categories = ["工作/学习", "娱乐休闲", "通讯交流", "信息检索", "系统操作", "其他"]
                for valid_cat in valid_categories:
                    if valid_cat in category:
                        result["category"] = valid_cat
                        break

    if not result["description"]:
        result["description"] = content[:100] if len(content) > 100 else content

    return result


def analyze_screen(image_base64: str, config: dict, app_context: dict = None) -> dict:
    api_config = config.get("api", {})
    api_key = api_config.get("api_key", "")
    base_url = api_config.get("base_url", "")
    model = api_config.get("model", "")

    if not api_key or not base_url:
        error_msg = "未配置 API 密钥或 Base URL"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "description": "", "category": "其他"}

    prompt = build_analysis_prompt(app_context)
    result = call_api(image_base64, api_key, base_url, model, prompt)

    if result.get("success"):
        parsed = parse_analysis_result(result.get("content", ""))
        return {
            "success": True,
            "description": parsed["description"],
            "category": parsed["category"],
            "raw_content": result.get("content", ""),
            "model": result.get("model", ""),
            "platform": result.get("platform", "")
        }
    else:
        error_msg = result.get("error", "未知错误")
        logger.error(f"API 调用失败: {error_msg}")
        return {"success": False, "error": error_msg, "description": "", "category": "其他"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_base64 = "dGVzdCBpbWFnZQ=="

    config = {
        "api": {"api_key": "", "base_url": "", "model": ""}
    }

    print("测试 AI API 模块...")


RELEVANCE_PROMPT = """请判断以下两个内容是否相关：
任务目标：{user_task}
当前活动：{current_activity}

请只回答"相关"或"不相关"，不要有其他文字。"""


def call_api_text(text: str, api_key: str, base_url: str, model: str) -> dict:
    """调用 OpenAI 兼容的文本 API"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": text
            }
        ],
        "max_tokens": 100
    }

    try:
        logger.info("调用文本 API...")
        response = requests.post(
            base_url,
            headers=headers,
            json=payload,
            timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()

        result = response.json()
        logger.info(f"文本 API 响应: {result}")

        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            logger.info("文本 API 调用成功")
            return {
                "success": True,
                "content": content,
                "model": model,
                "platform": "custom"
            }
        else:
            error_msg = result.get("error", {}).get("message", str(result))
            logger.error(f"文本 API 返回异常: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "platform": "custom"
            }

    except requests.exceptions.Timeout:
        error_msg = f"文本 API 请求超时 ({DEFAULT_TIMEOUT}s)"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "platform": "custom"}
    except requests.exceptions.RequestException as e:
        error_msg = f"文本 API 请求失败: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "platform": "custom"}
    except Exception as e:
        error_msg = f"文本 API 处理异常: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "platform": "custom"}


def check_activity_relevance(user_task: str, current_activity: str, config: dict) -> dict:
    api_config = config.get("api", {})
    api_key = api_config.get("api_key", "")
    base_url = api_config.get("base_url", "")
    model = api_config.get("model", "")

    if not api_key or not base_url:
        error_msg = "未配置 API 密钥或 Base URL"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}

    prompt = RELEVANCE_PROMPT.format(user_task=user_task, current_activity=current_activity)
    result = call_api_text(prompt, api_key, base_url, model)

    if result.get("success"):
        content = result.get("content", "").strip()
        is_relevant = "不相关" not in content and "相关" in content
        logger.info(f"相关性判断结果: content='{content}', is_relevant={is_relevant}")
        return {
            "success": True,
            "is_relevant": is_relevant,
            "raw_content": content,
            "model": result.get("model", ""),
            "platform": result.get("platform", "")
        }
    else:
        error_msg = result.get("error", "未知错误")
        logger.error(f"API 调用失败: {error_msg}")
        return {"success": False, "error": error_msg}
