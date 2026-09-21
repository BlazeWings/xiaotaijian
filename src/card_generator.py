"""卡片生成模块"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow 库未安装，卡片图片生成功能不可用")


def generate_card(analysis_result: dict, app_context: dict = None) -> dict:
    card_id = str(uuid.uuid4())
    timestamp = datetime.now()

    description = analysis_result.get("description") or analysis_result.get("activity", "未知活动")
    category = analysis_result.get("category", "其他")

    card = {
        "id": card_id,
        "timestamp": timestamp.isoformat(),
        "datetime_str": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "description": description,
        "category": category,
        "platform": analysis_result.get("platform", ""),
        "model": analysis_result.get("model", "")
    }

    # 前台应用上下文（AppObserver 提供）：排名按应用精确聚合用
    if app_context and app_context.get("app"):
        card["app"] = str(app_context["app"])
        title = str(app_context.get("title") or "").strip()
        if title:
            card["app_title"] = title[:200]

    logger.info(f"生成卡片: {card['datetime_str']} - {description} ({category})")
    return card


def save_card(card: dict, data_dir: str) -> bool:
    try:
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)

        cards_file = data_path / "cards.json"

        cards = []
        if cards_file.exists():
            try:
                with open(cards_file, "r", encoding="utf-8") as f:
                    cards = json.load(f)
                    if not isinstance(cards, list):
                        cards = []
            except json.JSONDecodeError:
                cards = []

        cards.append(card)

        with open(cards_file, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)

        logger.info(f"卡片已保存至: {cards_file}")
        return True

    except Exception as e:
        logger.error(f"保存卡片失败: {e}")
        return False


def load_cards_by_date(date_str: str, data_dir: str) -> list:
    try:
        data_path = Path(data_dir)
        cards_file = data_path / "cards.json"

        if not cards_file.exists():
            return []

        with open(cards_file, "r", encoding="utf-8") as f:
            cards = json.load(f)

        filtered_cards = [
            card for card in cards
            if card.get("datetime_str", "").startswith(date_str)
        ]

        logger.info(f"加载 {len(filtered_cards)} 条卡片记录 (日期: {date_str})")
        return filtered_cards

    except Exception as e:
        logger.error(f"加载卡片失败: {e}")
        return []


def load_all_cards(data_dir: str) -> list:
    try:
        data_path = Path(data_dir)
        cards_file = data_path / "cards.json"

        if not cards_file.exists():
            return []

        with open(cards_file, "r", encoding="utf-8") as f:
            cards = json.load(f)

        logger.info(f"加载全部 {len(cards)} 条卡片记录")
        return cards

    except Exception as e:
        logger.error(f"加载卡片失败: {e}")
        return []


def create_card_image(
    screenshot_path: str,
    card_data: dict,
    output_path: str
) -> dict:
    if not PIL_AVAILABLE:
        return {"success": False, "error": "Pillow 库未安装"}

    try:
        timestamp = datetime.now()

        try:
            screenshot_img = Image.open(screenshot_path)
        except Exception:
            screenshot_img = Image.new("RGB", (800, 450), color=(50, 50, 50))

        max_width = 800
        if screenshot_img.width > max_width:
            ratio = max_width / screenshot_img.width
            new_height = int(screenshot_img.height * ratio)
            screenshot_img = screenshot_img.resize((max_width, new_height))

        card_height = screenshot_img.height + 120
        card_img = Image.new("RGB", (max_width, card_height), color=(30, 30, 30))

        card_img.paste(screenshot_img, (0, 0))

        draw = ImageDraw.Draw(card_img)

        try:
            font = ImageFont.truetype("msyh.ttc", 16)
        except Exception:
            try:
                font = ImageFont.truetype("arial.ttf", 16)
            except Exception:
                font = ImageFont.load_default()

        info_y = screenshot_img.height + 20
        time_str = card_data.get("datetime_str", timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        draw.text((20, info_y), f"时间: {time_str}", fill=(200, 200, 200), font=font)
        draw.text((20, info_y + 30), f"活动: {card_data.get('description', '')}", fill=(255, 255, 255), font=font)

        category_colors = {
            "工作/学习": (100, 149, 237),
            "娱乐休闲": (255, 165, 0),
            "通讯交流": (50, 205, 50),
            "信息检索": (255, 215, 0),
            "系统操作": (147, 112, 219),
            "其他": (169, 169, 169)
        }
        color = category_colors.get(card_data.get("category", "其他"), (169, 169, 169))
        draw.text((20, info_y + 60), f"类别: {card_data.get('category', '其他')}", fill=color, font=font)

        card_img.save(output_path, "PNG")
        logger.info(f"卡片图片已保存至: {output_path}")

        return {"success": True, "card_path": output_path}

    except Exception as e:
        error_msg = f"生成卡片图片失败: {e}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("测试卡片生成功能...")

    analysis = {
        "description": "正在编写 Python 代码",
        "category": "工作/学习",
        "platform": "zhipu",
        "model": "glm-4v-flash"
    }

    card = generate_card(analysis)
    print(f"生成的卡片: {json.dumps(card, ensure_ascii=False, indent=2)}")

    print("测试完成!")
