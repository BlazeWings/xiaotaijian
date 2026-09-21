"""每日报告生成模块"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


CATEGORY_SIMILARITY = {
    "工作/学习": ["工作/学习", "系统操作"],
    "娱乐休闲": ["娱乐休闲", "通讯交流"],
    "通讯交流": ["通讯交流", "娱乐休闲"],
    "信息检索": ["信息检索", "工作/学习"],
    "系统操作": ["系统操作", "工作/学习"],
    "其他": ["其他"]
}


def load_cards_by_date(date_str: str, data_dir: str) -> List[dict]:
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

        return filtered_cards

    except Exception as e:
        logger.error(f"加载卡片失败: {e}")
        return []


def load_recent_cards(minutes: int, data_dir: str) -> List[dict]:
    try:
        data_path = Path(data_dir)
        cards_file = data_path / "cards.json"

        if not cards_file.exists():
            return []

        with open(cards_file, "r", encoding="utf-8") as f:
            cards = json.load(f)

        now = datetime.now()
        cutoff_time = now - timedelta(minutes=minutes)

        recent_cards = []
        for card in cards:
            card_time_str = card.get("datetime_str", "")
            try:
                card_time = datetime.strptime(card_time_str, "%Y-%m-%d %H:%M:%S")
                if card_time >= cutoff_time:
                    recent_cards.append(card)
            except ValueError:
                continue

        return recent_cards

    except Exception as e:
        logger.error(f"加载最近卡片失败: {e}")
        return []


def is_similar_category(cat1: str, cat2: str) -> bool:
    if cat1 == cat2:
        return True
    similar_cats = CATEGORY_SIMILARITY.get(cat1, [])
    return cat2 in similar_cats


def is_similar_description(desc1: str, desc2: str) -> bool:
    if not desc1 or not desc2:
        return False

    desc1 = desc1.lower()
    desc2 = desc2.lower()

    if desc1 == desc2:
        return True

    keywords1 = set(desc1.split())
    keywords2 = set(desc2.split())

    if not keywords1 or not keywords2:
        return False

    common = keywords1 & keywords2
    union = keywords1 | keywords2

    jaccard = len(common) / len(union) if union else 0
    return jaccard >= 0.5


def merge_consecutive_cards(cards: List[dict]) -> List[dict]:
    if not cards:
        return []

    sorted_cards = sorted(cards, key=lambda x: x.get("datetime_str", ""))

    merged = []
    current_item = {
        "start_time": sorted_cards[0].get("datetime_str", ""),
        "end_time": sorted_cards[0].get("datetime_str", ""),
        "description": sorted_cards[0].get("description", ""),
        "category": sorted_cards[0].get("category", "其他"),
        "count": 1
    }
    merged.append(current_item)

    for i in range(1, len(sorted_cards)):
        card = sorted_cards[i]
        card_time_str = card.get("datetime_str", "")

        try:
            card_time = datetime.strptime(card_time_str, "%Y-%m-%d %H:%M:%S")
            current_end_time = datetime.strptime(merged[-1]["end_time"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        time_diff = (card_time - current_end_time).total_seconds()

        if (time_diff <= 300 and
            is_similar_category(merged[-1]["category"], card.get("category", "其他")) and
            is_similar_description(merged[-1]["description"], card.get("description", ""))):
            merged[-1]["end_time"] = card_time_str
            merged[-1]["count"] += 1
        else:
            merged.append({
                "start_time": card_time_str,
                "end_time": card_time_str,
                "description": card.get("description", ""),
                "category": card.get("category", "其他"),
                "count": 1
            })

    return merged


def generate_time_range_str(start_time: str, end_time: str) -> str:
    try:
        start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")

        start_str = start.strftime("%H:%M")
        end_str = end.strftime("%H:%M")

        if start.date() == end.date():
            return f"{start_str} - {end_str}"
        else:
            return f"{start.strftime('%m-%d %H:%M')} - {end.strftime('%m-%d %H:%M')}"
    except ValueError:
        return f"{start_time} - {end_time}"


def generate_daily_report(date_str: str, data_dir: str, output_path: Optional[str] = None) -> str:
    cards = load_cards_by_date(date_str, data_dir)

    if not cards:
        logger.info(f"日期 {date_str} 没有卡片记录")
        return ""

    merged_cards = merge_consecutive_cards(cards)

    if output_path is None:
        report_dir = Path(data_dir) / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        output_path = report_dir / f"report_{date_str}.txt"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"{'='*60}\n")
        f.write(f"屏幕监管日报 - {date_str}\n")
        f.write(f"{'='*60}\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"总记录数: {len(cards)}\n")
        f.write(f"合并后: {len(merged_cards)}\n")
        f.write(f"{'='*60}\n\n")

        category_stats = {}
        for card in cards:
            cat = card.get("category", "其他")
            category_stats[cat] = category_stats.get(cat, 0) + 1

        f.write("【活动统计】\n")
        for cat, count in sorted(category_stats.items(), key=lambda x: -x[1]):
            percentage = count / len(cards) * 100
            f.write(f"  {cat}: {count}次 ({percentage:.1f}%)\n")
        f.write("\n")

        f.write("【活动时间线】\n")
        f.write("-" * 60 + "\n")

        for i, item in enumerate(merged_cards, 1):
            time_range = generate_time_range_str(item["start_time"], item["end_time"])
            f.write(f"{i}. {time_range}\n")
            f.write(f"   活动: {item['description']}\n")
            f.write(f"   类别: {item['category']}\n")
            if item['count'] > 1:
                f.write(f"   (合并了{item['count']}条相似记录)\n")
            f.write("\n")

        f.write("-" * 60 + "\n")
        f.write("报告生成完毕\n")

    logger.info(f"日报已生成: {output_path}")
    return str(output_path)


def generate_realtime_summary(minutes: int, data_dir: str) -> str:
    cards = load_recent_cards(minutes, data_dir)

    if not cards:
        return f"最近 {minutes} 分钟内没有活动记录"

    merged = merge_consecutive_cards(cards)

    lines = []
    lines.append(f"=== 最近 {minutes} 分钟活动摘要 ===\n")

    for i, item in enumerate(merged[-5:], 1):
        time_range = generate_time_range_str(item["start_time"], item["end_time"])
        lines.append(f"{i}. {time_range} | {item['description']} ({item['category']})")

    return "\n".join(lines)


def check_and_generate_daily_report(data_dir: str, date_str: Optional[str] = None) -> Optional[str]:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    report_dir = Path(data_dir) / "report"
    report_file = report_dir / f"report_{date_str}.txt"

    if report_file.exists():
        logger.info(f"今日报告已存在: {report_file}")
        return None

    return generate_daily_report(date_str, data_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("测试报告生成...")

    result = generate_daily_report("2026-03-30", "data")
    print(f"报告生成结果: {result}")

    summary = generate_realtime_summary(60, "data")
    print(f"\n实时摘要:\n{summary}")
