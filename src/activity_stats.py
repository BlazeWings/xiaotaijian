"""活动统计与排名模块（纯逻辑，无 GUI 依赖，可独立测试）

数据来源：data/cards.json，每条卡片代表一次截图分析结果：
    {timestamp, datetime_str, description, category, platform, model}

核心概念：
- 每张卡片代表一个时间段：从该卡片时刻到下一张卡片时刻（最后一张到"现在"）。
- 时间段长度会被封顶（rank_cap_seconds），避免长时间空闲/关机拉高排名。
- "时间排名"：把相似事件（同类别 + 描述相似度）归类，按累计时长排序。
"""
import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CAP_SECONDS = 15 * 60  # 单张卡片最多计入的时长（秒）
SIMILAR_THRESHOLD = 0.5        # 描述相似度阈值（bigram 包含度）


def load_cards(data_dir: str) -> list:
    """读取全部卡片并按时间升序排序。文件损坏/写入中时返回 []。"""
    cards_file = Path(data_dir) / "cards.json"
    if not cards_file.exists():
        return []
    try:
        with open(cards_file, "r", encoding="utf-8") as f:
            cards = json.load(f)
        if not isinstance(cards, list):
            return []
        cards = [c for c in cards if isinstance(c, dict) and c.get("datetime_str")]
        cards.sort(key=lambda c: str(c.get("datetime_str", "")))
        return cards
    except Exception as e:
        logger.warning("读取卡片失败（可能正在写入）: %s", e)
        return []


def _parse_dt(card: dict):
    ts = card.get("timestamp") or card.get("datetime_str")
    if not ts:
        return None
    try:
        s = str(ts).strip()
        if "T" in s:
            return datetime.fromisoformat(s)
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def compute_slices(cards: list, now=None, cap_seconds: int = DEFAULT_CAP_SECONDS) -> list:
    """把卡片序列切成时间段：[{card, start, duration}]，duration 已封顶。"""
    if now is None:
        now = datetime.now()
    parsed = []
    for c in cards:
        dt = _parse_dt(c)
        if dt is not None:
            parsed.append((dt, c))
    parsed.sort(key=lambda x: x[0])
    slices = []
    for i, (dt, card) in enumerate(parsed):
        nxt = parsed[i + 1][0] if i + 1 < len(parsed) else now
        dur = min(max((nxt - dt).total_seconds(), 0.0), cap_seconds)
        slices.append({"card": card, "start": dt, "duration": dur})
    return slices


def _bigrams(text: str) -> set:
    """中文字符 bigram 集合，用于快速相似度比较。"""
    norm = "".join(str(text).split()).lower()
    if len(norm) < 2:
        return {norm} if norm else set()
    return {norm[i:i + 2] for i in range(len(norm) - 1)}


def _similarity(seeds_a: set, seeds_b: set) -> float:
    """bigram 包含度：交集 / 较小集合大小。"""
    if not seeds_a or not seeds_b:
        return 0.0
    inter = len(seeds_a & seeds_b)
    return inter / min(len(seeds_a), len(seeds_b))


def cluster_slices(slices: list, threshold: float = SIMILAR_THRESHOLD) -> list:
    """把时间段按（类别 + 描述相似度）归类。

    使用 seed 索引加速：只与共享任意 bigram 的既有分组比较。
    返回分组列表：[{category, rep, label, count, total, counter, slices}]。
    """
    groups = []
    seed_index = {}  # bigram -> set(group_id)

    for sl in slices:
        card = sl["card"]
        cat = str(card.get("category") or "其他")
        desc = str(card.get("description") or "未知活动")
        seeds = _bigrams(desc)

        candidates = set()
        for s in seeds:
            candidates |= seed_index.get(s, set())

        target = None
        for gid in candidates:
            g = groups[gid]
            if g["category"] != cat:
                continue
            if _similarity(g["seeds"], seeds) >= threshold:
                target = g
                break

        if target is None:
            target = {
                "category": cat,
                "rep": desc,
                "seeds": seeds,
                "count": 0,
                "total": 0.0,
                "counter": Counter(),
                "slices": [],
            }
            gid = len(groups)
            groups.append(target)
            for s in seeds:
                seed_index.setdefault(s, set()).add(gid)

        target["count"] += 1
        target["total"] += sl["duration"]
        target["counter"][desc] += 1
        target["slices"].append(sl)

    for g in groups:
        g["label"] = g["counter"].most_common(1)[0][0] if g["counter"] else g["rep"]

    # 第二遍：按“最常见描述”（label）再做分组级合并，
    # 修复第一遍因代表描述不同导致的分裂（如“编辑或审阅文档” vs “用户正在编辑或审阅文档”）。
    groups = _merge_similar_groups(groups, threshold)
    return groups


def _merge_similar_groups(groups: list, threshold: float = SIMILAR_THRESHOLD) -> list:
    """把代表描述相似的分组合并，返回新列表（保持原结构字段）。"""
    merged = []
    index = {}  # bigram -> set(merged_id)

    for g in groups:
        label = g["counter"].most_common(1)[0][0] if g["counter"] else g["rep"]
        seeds = _bigrams(label)

        candidates = set()
        for sd in seeds:
            candidates |= index.get(sd, set())

        target = None
        for gid in candidates:
            m = merged[gid]
            if m["category"] != g["category"]:
                continue
            if _similarity(m["seeds"], seeds) >= threshold:
                target = m
                break

        if target is None:
            target = {
                "category": g["category"],
                "rep": g["rep"],
                "seeds": seeds,
                "count": 0,
                "total": 0.0,
                "counter": Counter(),
                "slices": [],
            }
            gid = len(merged)
            merged.append(target)
            for sd in seeds:
                index.setdefault(sd, set()).add(gid)

        target["count"] += g["count"]
        target["total"] += g["total"]
        target["counter"].update(g["counter"])
        target["slices"].extend(g["slices"])

    for g in merged:
        g["label"] = g["counter"].most_common(1)[0][0] if g["counter"] else g["rep"]
    return merged


def rank_groups(groups: list, top: int = 8) -> list:
    """按累计时长降序排名，返回前 top 名。"""
    ranked = sorted(groups, key=lambda g: g["total"], reverse=True)[:top]
    total = sum(g["total"] for g in groups) or 1.0
    return [
        {
            "rank": i + 1,
            "label": g["label"],
            "category": g["category"],
            "count": g["count"],
            "total": g["total"],
            "share": g["total"] / total,
        }
        for i, g in enumerate(ranked)
    ]


# ---------- 应用精确视图（AppObserver 数据） ----------
def _resolve_alias(app_key: str, meta: dict, aliases: dict, title: str = "") -> str:
    """应用显示名：配置 > 内置表 > app_meta 学习 > 进程名去扩展名。"""
    from .app_observer import KNOWN_ALIASES  # 延迟导入，避免模块级依赖
    if aliases and app_key in aliases:
        return aliases[app_key]
    if app_key in KNOWN_ALIASES:
        return KNOWN_ALIASES[app_key]
    m = meta.get(app_key) or {}
    if m.get("alias"):
        return m["alias"]
    if title and " - " in title:
        cand = title.rsplit(" - ", 1)[-1].strip()
        if 2 <= len(cand) <= 12:
            return cand
    return app_key.rsplit(".", 1)[0] if "." in app_key else app_key


def _build_app_view(data_dir, cards, now, scope, top, history_max, aliases=None):
    """应用精确视图：时长=会话统计（秒级精确），语义标签/类别=AI 卡片。

    无会话数据时返回 None（调用方回退旧路径）。
    """
    from . import app_observer

    db_path = Path(data_dir) / "app_usage.db"
    today = now.strftime("%Y-%m-%d")
    if scope == "today":
        date_from = date_to = today
    elif scope == "week":
        date_from = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        date_to = today
    else:
        date_from = date_to = None

    totals = app_observer.load_app_totals(db_path, date_from, date_to)
    if not totals:
        return None

    meta = app_observer.load_app_meta(db_path)
    state = app_observer.load_app_state(data_dir)
    aliases = {str(k).lower(): str(v) for k, v in (aliases or {}).items()}

    # 范围内带 app 字段的卡片：提供语义标签与类别投票
    desc_counter = {}
    cat_counter = {}
    for c in cards:
        app = str(c.get("app") or "").lower()
        if not app:
            continue
        desc_counter.setdefault(app, Counter())[str(c.get("description") or "")] += 1
        cat_counter.setdefault(app, Counter())[str(c.get("category") or "其他")] += 1

    def alias_of(app_key):
        return _resolve_alias(app_key, meta, aliases)

    rows = []
    for app, total in totals.items():
        alias = alias_of(app)
        desc = desc_counter.get(app, Counter()).most_common(1)
        label_core = desc[0][0] if desc and desc[0][0] else ""
        mcat = (meta.get(app) or {}).get("category")
        cc = cat_counter.get(app, Counter()).most_common(1)
        cat = mcat or (cc[0][0] if cc else "其他")
        label = f"{alias} · {label_core}" if label_core else alias
        rows.append({
            "app": app,
            "label": label,
            "category": cat,
            "count": sum(desc_counter.get(app, Counter()).values()),
            "total": float(total),
        })

    # 当前会话：进行中时长实时并入（会话结束才落库）
    cur_app = None
    cur_app_elapsed = 0.0
    if state and state.get("app"):
        s_app = str(state["app"]).lower()
        try:
            s_start_dt = datetime.fromisoformat(str(state.get("start")))
            cur_app_elapsed = max((now - s_start_dt).total_seconds(), 0.0)
        except Exception:
            pass
        matched = False
        for r in rows:
            if r["app"] == s_app:
                r["total"] += cur_app_elapsed
                matched = True
                break
        if not matched:
            rows.append({
                "app": s_app,
                "label": state.get("alias") or alias_of(s_app),
                "category": (meta.get(s_app) or {}).get("category") or "其他",
                "count": 0,
                "total": cur_app_elapsed,
            })
        cur_app = {
            "app": s_app,
            "title": state.get("title") or "",
            "start": state.get("start") or "",
            "alias": state.get("alias") or alias_of(s_app),
            "is_idle": bool(state.get("is_idle")),
        }
    elif state and state.get("is_idle"):
        cur_app = {"is_idle": True}

    grand = sum(r["total"] for r in rows) or 1.0
    rows.sort(key=lambda r: r["total"], reverse=True)
    ranking = [
        {
            "rank": i + 1,
            "app": r["app"],
            "label": r["label"],
            "category": r["category"],
            "count": r["count"],
            "total": r["total"],
            "share": r["total"] / grand,
        }
        for i, r in enumerate(rows[:top])
    ]

    live = {
        "last_card_dt": None,
        "open_seconds": 0.0,
        "open_at_build": 0.0,
        "current_rank_index": -1,
        "app_start": None,
    }
    if cur_app and cur_app.get("app"):
        idx = next((i for i, r in enumerate(ranking) if r.get("app") == cur_app["app"]), -1)
        if idx == -1:
            full_row = next((r for r in rows if r["app"] == cur_app["app"]), None)
            if full_row is not None:
                ranking.append({
                    "rank": len(ranking) + 1,
                    "app": full_row["app"],
                    "label": full_row["label"],
                    "category": full_row["category"],
                    "count": full_row["count"],
                    "total": full_row["total"],
                    "share": full_row["total"] / grand,
                    "is_current": True,
                })
                idx = len(ranking) - 1
        live["current_rank_index"] = idx
        live["app_start"] = cur_app.get("start") or None
        live["open_seconds"] = cur_app_elapsed
        live["open_at_build"] = cur_app_elapsed
    if cards:
        live["last_card_dt"] = cards[-1].get("timestamp") or cards[-1].get("datetime_str") or ""

    # 历史卡片附应用别名，面板直接显示
    alias_map = {app: alias_of(app) for app in totals}
    for c in cards:
        app = str(c.get("app") or "").lower()
        if app:
            c["app_alias"] = alias_map.get(app) or alias_of(app)

    return {
        "current": cards[-1] if cards else None,
        "history": list(reversed(cards[-history_max:])) if cards else [],
        "ranking": ranking,
        "card_count": len(cards),
        "total_seconds": grand,
        "scope": scope,
        "updated_at": now.strftime("%H:%M:%S"),
        "live": live,
        "current_app": cur_app,
        "mode": "app",
    }


def build_view(
    data_dir: str,
    now=None,
    scope: str = "today",
    top: int = 8,
    cap_seconds: int = DEFAULT_CAP_SECONDS,
    history_max: int = 30,
    max_cards: int = 0,
    aliases: dict = None,
) -> dict:
    """一次生成面板所需的完整视图数据。

    scope: "today" 只看今天；"week" 看本周（周一 00:00 起）；"all" 看全部。
    max_cards: "all" 范围最多统计的最近卡片数；0（默认）= 不限制，全部历史都统计。
    返回 {current, history, ranking, card_count, total_seconds, scope}。

    若存在应用会话数据（data/app_usage.db 由 AppObserver 写入），切换到
    「应用精确视图」：排名按应用聚合、时长取会话统计（精确到秒），AI 卡片
    提供语义标签与类别；否则回退到卡片描述聚类（旧路径）。
    """
    if now is None:
        now = datetime.now()

    cards = load_cards(data_dir)
    if scope == "today":
        today = now.strftime("%Y-%m-%d")
        cards = [c for c in cards if str(c.get("datetime_str", "")).startswith(today)]
    elif scope == "week":
        monday = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        cards = [
            c for c in cards
            if monday <= str(c.get("datetime_str", "")) <= now_str
        ]
    else:
        # "all"：默认统计全部历史；仅当显式配置了正数上限时才截断最近 N 条
        if max_cards and max_cards > 0:
            cards = cards[-max_cards:]

    # 应用精确视图（AppObserver 数据可用时）
    try:
        app_view = _build_app_view(data_dir, cards, now, scope, top, history_max, aliases)
    except Exception as e:
        logger.warning("应用视图构建失败，回退卡片聚类: %s", e)
        app_view = None
    if app_view is not None:
        return app_view

    slices = compute_slices(cards, now=now, cap_seconds=cap_seconds)
    groups = cluster_slices(slices)

    # 实时增量信息：最后一张卡片（当前事件）所属分组的时长会随“现在”增长，
    # UI 心跳据此滚动更新，无需重读文件。
    live = {
        "last_card_dt": None,
        "open_seconds": 0.0,
        "open_at_build": 0.0,
        "current_rank_index": -1,
    }
    current_group = None
    if slices:
        last_slice = slices[-1]
        live["last_card_dt"] = (
            cards[-1].get("timestamp") or cards[-1].get("datetime_str") or ""
        )
        live["open_seconds"] = last_slice["duration"]
        live["open_at_build"] = last_slice["duration"]
        for g in groups:
            if g["slices"] and g["slices"][-1] is last_slice:
                current_group = g
                break

    ranking = rank_groups(groups, top=top)
    total_all = sum(g["total"] for g in groups) or 1.0

    if current_group is not None:
        # 找到当前分组在排名中的位置（按 label+category 匹配）
        for i, r in enumerate(ranking):
            if r["label"] == current_group["label"] and r["category"] == current_group["category"]:
                live["current_rank_index"] = i
                break
        if live["current_rank_index"] == -1:
            # 当前分组未进前 top：追加一行并标记“当前”，保证实时可见
            ranking = ranking + [{
                "rank": len(ranking) + 1,
                "label": current_group["label"],
                "category": current_group["category"],
                "count": current_group["count"],
                "total": current_group["total"],
                "share": current_group["total"] / total_all,
                "is_current": True,
            }]
            live["current_rank_index"] = len(ranking) - 1

    return {
        "current": cards[-1] if cards else None,
        "history": list(reversed(cards[-history_max:])) if cards else [],
        "ranking": ranking,
        "card_count": len(cards),
        "total_seconds": sum(sl["duration"] for sl in slices),
        "scope": scope,
        "updated_at": now.strftime("%H:%M:%S"),
        "live": live,
    }


def format_duration(seconds) -> str:
    """把秒数格式化为中文时长，如 45秒 / 12分钟 / 1小时32分。"""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}秒"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}分钟" if s == 0 else f"{m}分{s:02d}秒"
    h, m2 = divmod(m, 60)
    if h < 24:
        return f"{h}小时{m2}分"
    d, h2 = divmod(h, 24)
    return f"{d}天{h2}小时"


def format_hhmm(card: dict) -> str:
    """从卡片取 "HH:MM"。"""
    ds = str(card.get("datetime_str", ""))
    return ds[11:16] if len(ds) >= 16 else ds
