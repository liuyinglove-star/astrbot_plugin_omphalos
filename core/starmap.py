"""意识海 · 记忆星图：把翁法罗斯的记忆库映射成可交互星图。

设计参照「每一颗星都是一段记忆」，按记忆性质分成五档：

    核心·恒星  chronicle 的轮次总结（最重的骨架）
    长期·亮星  kind=牺牲（黄金裔献身）
    编年·行星  kind=台词（角色说过的话）
    每日·尘星  kind=事件（日常）
    归档·灰星  kind=野史

坐标形态：**三维修正的「8」字环（figure-8 / 双纽线）**。

    不是莫比乌斯带面，也不是从中心射出的螺旋臂，而是一条细的发光路径
    绕成左右两片、在中心交叉，两片分别向上向下翻折：

        x = R · sin(t)                      主轴，左右两瓣
        y = R · squash · sin(2t) / 2        腰部收束，让两端在中心交叉
        z = R · twist · cos(t)              一次完整上下，形成扭转

    t = 90°  右瓣最高
    t = 270° 左瓣最低
    t = 0°、180° 在中心交叉

    记忆映射：
        t  = 时间顺序（按排序秩，均匀铺满一圈，首尾相接）
        w  = 垂直于曲线的横向散布（带出银河般的体积感）
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

# 五档记忆的元信息：key -> (中文名, 横向散布系数, 星点大小, 颜色, 亮度)
# 第二项决定离曲线的横向距离，0 表示紧贴曲线
TIERS: dict[str, tuple[str, float, float, str, float]] = {
    "core": ("核心·恒星", 0.00, 3.2, "#fff8e7", 1.0),
    "long": ("长期·亮星", 0.55, 2.0, "#ffd6f5", 0.85),
    "chronicle": ("编年·行星", 0.90, 1.3, "#9fd4ff", 0.7),
    "daily": ("每日·尘星", 1.25, 0.8, "#b9c6ff", 0.5),
    "archive": ("归档·灰星", 1.55, 0.6, "#8a8fa8", 0.35),
}

# 8 字环参数
RING_R = 1.0        # 主轴半径
RING_SQUASH = 0.78  # y 方向压扁
RING_TWIST = 0.45   # z 方向扭转
SPREAD = 0.16       # 横向散布的最大幅度

# kind -> tier
KIND_TIER = {
    "牺牲": "long",
    "台词": "chronicle",
    "事件": "daily",
    "野史": "archive",
}


def _stable_noise(seed: str, idx: int) -> float:
    """用字符串哈希生成稳定的伪随机数，保证同一颗星每次位置一致。

    Args:
        seed: 种子字符串。
        idx: 需要的第几个数。

    Returns:
        float: [0, 1) 之间的数。
    """
    h = hashlib.md5(f"{seed}:{idx}".encode()).digest()
    return int.from_bytes(h[:4], "big") / 0xFFFFFFFF


def eight_curve(t: float) -> tuple[float, float, float]:
    """8 字环的中心曲线。

    Args:
        t: 参数 0→2π。

    Returns:
        tuple[float, float, float]: 曲线上的 (x, y, z)。
    """
    return (
        RING_R * math.sin(t),
        RING_R * RING_SQUASH * math.sin(2 * t) / 2.0,
        RING_R * RING_TWIST * math.cos(t),
    )


def point_on_ring(t: float, lateral: float, vertical: float) -> tuple[float, float, float]:
    """把曲线上的点加上横向/竖直偏移。

    横向用曲线切线叉乘竖直方向得到，保证散开的方向垂直于路径，
    粒子才会像银河一样「围着」路径铺开，而不是糊成一团。

    Args:
        t: 曲线参数。
        lateral: 横向偏移量（沿法向）。
        vertical: 竖直偏移量。

    Returns:
        tuple[float, float, float]: 最终世界坐标。
    """
    x, y, z = eight_curve(t)
    # 用有限差分求切线，再与 up 叉乘得到法向
    dt = 1e-3
    x2, y2, z2 = eight_curve(t + dt)
    tx, ty, tz = x2 - x, y2 - y, z2 - z
    norm = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
    tx, ty, tz = tx / norm, ty / norm, tz / norm

    # 法向 = 切线 × up(0,0,1)
    nx = ty * 1.0 - tz * 0.0
    ny = tz * 0.0 - tx * 1.0
    nz = 0.0
    nlen = math.sqrt(nx * nx + ny * ny) or 1.0
    nx, ny = nx / nlen, ny / nlen

    return (
        x + nx * lateral,
        y + ny * lateral,
        z + vertical,
    )


def build_star_map(archive: dict[str, Any]) -> dict[str, Any]:
    """把归档数据转成星图数据。

    Args:
        archive: Demiurge_Archives.json 的内容。

    Returns:
        dict[str, Any]: 含 stars / stats 的星图数据，每颗星带 x/y/z 世界坐标。
    """
    fragments = list(archive.get("fragments") or [])
    archived = list(archive.get("archived_fragments") or [])
    chronicle = list(archive.get("chronicle") or [])
    round_now = int(archive.get("round_no") or 1)

    # 合并碎片，按 fid+round_no 去重
    seen: set[tuple[int, int]] = set()
    merged: list[dict[str, Any]] = []
    for f in fragments + archived:
        key = (int(f.get("round_no", 0)), int(f.get("fid", 0)))
        if key in seen:
            continue
        seen.add(key)
        merged.append(f)

    stars: list[dict[str, Any]] = []

    # ---- 核心：轮次总结，沿环均匀铺开作为骨架 ----
    valid_chronicle = [
        c for c in chronicle
        if str(c.get("summary") or "").strip() not in ("", "（本轮无记录）")
    ]
    n_core = max(1, len(valid_chronicle))
    for i, c in enumerate(valid_chronicle):
        rn = int(c.get("round_no", 0))
        t = 2 * math.pi * (i / n_core)
        summary = str(c.get("summary") or "").strip()
        x, y, z = eight_curve(t)
        stars.append(
            {
                "id": f"core-{rn}",
                "tier": "core",
                "kind": "轮次",
                "name": f"第 {rn} 轮",
                "text": summary[:300],
                "round_no": rn,
                "ts": float(c.get("started_at", 0) or 0),
                "t": t,
                "x": x, "y": y, "z": z,
            }
        )

    # ---- 四类碎片，围绕 8 字曲线铺开 ----
    # 按时间排序后用「秩」映射到环上，避免时间戳聚集导致全挤在一段
    merged.sort(key=lambda f: float(f.get("ts", 0) or 0))
    total_frag = max(1, len(merged))
    for rank, f in enumerate(merged):
        kind = str(f.get("kind", "事件"))
        tier = KIND_TIER.get(kind, "daily")
        ts = float(f.get("ts", 0) or 0)
        rn = int(f.get("round_no", 0))
        name = str(f.get("name", "未知"))
        text = str(f.get("text", ""))

        tier_info = TIERS[tier]
        spread_k = tier_info[1]

        # t 由排序秩决定，绕环一周首尾相接
        t = 2 * math.pi * (rank / total_frag)
        t += (_stable_noise(f"{name}{ts}", 0) - 0.5) * 0.10
        t %= 2 * math.pi

        # 横向散布：层级决定倍数，噪声决定具体位置
        lateral = (_stable_noise(f"{name}{rn}{f.get('fid')}", 1) - 0.5) * 2.0 * SPREAD * spread_k
        # 竖直散布：稍微给一点厚度
        vertical = (_stable_noise(f"{name}{ts}", 3) - 0.5) * 0.055 * (0.5 + spread_k)

        x, y, z = point_on_ring(t, lateral, vertical)

        stars.append(
            {
                "id": f"{tier}-{rn}-{f.get('fid')}",
                "tier": tier,
                "kind": kind,
                "name": name,
                "text": text[:300],
                "round_no": rn,
                "ts": ts,
                "t": t,
                "x": x, "y": y, "z": z,
            }
        )

    # ---- 统计 ----
    counts: dict[str, int] = {k: 0 for k in TIERS}
    for s in stars:
        counts[s["tier"]] += 1

    # ---- 角色档案：按出现次数排序，供左侧立绘卡展示 ----
    profiles = build_profiles(merged, round_now)

    return {
        "stars": stars,
        "profiles": profiles,
        "stats": {
            "total": len(stars),
            "round_no": round_now,
            "counts": counts,
            "shape": "figure8",
            "ring_r": RING_R,
            "ring_squash": RING_SQUASH,
            "ring_twist": RING_TWIST,
            "tiers": {
                k: {
                    "label": v[0],
                    "size": v[2],
                    "color": v[3],
                    "brightness": v[4],
                    "count": counts[k],
                }
                for k, v in TIERS.items()
            },
        },
    }


# 角色代号与分类的固定映射（参照原型卡片上的字段）
ROLE_META: dict[str, tuple[str, str]] = {
    "翁法罗斯": ("WORLD", "世界"),
    "德谬歌": ("DEMIURGE", "容器"),
    "昔涟": ("KEEPER", "岁月"),
    "白厄": ("STRIKE", "劫余"),
    "阿格莱雅": ("WEAVER", "浪漫"),
    "那刻夏": ("SEER", "理性"),
    "缇宝": ("GATEWAY", "门径"),
    "万敌": ("WAR", "纷争"),
    "遐蝶": ("MOTH", "死亡"),
    "风堇": ("HEAL", "疗愈"),
    "海瑟音": ("SONG", "海洋"),
    "刻律德菈": ("LAW", "律令"),
    "赛飞儿": ("SWIFT", "疾行"),
    "丹恒·腾荒": ("DRAGON", "持明"),
}

# 分类池，按编号取模分配
CATEGORIES = ["黄金裔", "劫余", "岁月", "命运", "律令"]


def build_profiles(fragments: list[dict[str, Any]], round_now: int) -> list[dict[str, Any]]:
    """按角色聚合出档案卡数据。

    Args:
        fragments: 已合并的记忆碎片（dict 列表）。
        round_now: 当前轮次。

    Returns:
        list[dict[str, Any]]: 按记忆条数降序的档案列表。
    """
    agg: dict[str, dict[str, Any]] = {}
    for f in fragments:
        name = str(f.get("name", "未知"))
        if name not in agg:
            agg[name] = {
                "name": name,
                "count": 0,
                "kinds": {},
                "latest_text": "",
                "latest_ts": 0.0,
                "first_round": int(f.get("round_no", 0)),
            }
        a = agg[name]
        a["count"] += 1
        kind = str(f.get("kind", ""))
        a["kinds"][kind] = a["kinds"].get(kind, 0) + 1
        ts = float(f.get("ts", 0) or 0)
        if ts >= a["latest_ts"]:
            a["latest_ts"] = ts
            a["latest_text"] = str(f.get("text", ""))[:120]
        a["first_round"] = min(a["first_round"], int(f.get("round_no", 0)))

    out: list[dict[str, Any]] = []
    for idx, (name, a) in enumerate(sorted(agg.items(), key=lambda kv: -kv[1]["count"])):
        code, cat = ROLE_META.get(name, ("UNKNOWN", CATEGORIES[idx % len(CATEGORIES)]))
        # 用名字哈希生成稳定的编号与代码号，保证每次一致
        seed = _stable_noise(name, 5)
        number = int(seed * 88) + 1
        serial = f"MLS-CRB-{number:03d}"
        # 「距离」用最新时间与当前时间的差，以万为单位滚动
        distance = abs(round_now - a["first_round"]) * 1_000_000 + int(seed * 900_000)

        reasons = a["kinds"]
        dominant = max(reasons.items(), key=lambda kv: kv[1])[0] if reasons else "事件"

        out.append(
            {
                "name": name,
                "code": code,
                "number": number,
                "category": cat,
                "serial": serial,
                "count": a["count"],
                "dominant": dominant,
                "distance": distance,
                "latest_text": a["latest_text"],
                "first_round": a["first_round"],
                "status": "已陨世" if "牺牲" in reasons else "在案",
            }
        )
    return out
