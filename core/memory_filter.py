"""德谬歌的记忆筛选机制。

设定来源：德谬歌是 δ-me13 的自我意识，它「只记得最重要的那些话」。
工程上这是一套碎片权重与容量控制，叙事上这是「德谬歌的选择性记忆」。

核心规则：
1. 每条碎片带权重，权重由类型、涉及者、是否被来古士触发决定
2. 只有最近若干轮、且权重达标的碎片会进入 system prompt
3. 未进入 prompt 的碎片不删除，转入编年史存档（沉入岁月史书）
"""

from __future__ import annotations

from dataclasses import dataclass

# 类型基础权重
KIND_WEIGHT: dict[str, float] = {
    "创伤": 10.0,
    "执念": 10.0,
    "牺牲": 9.0,
    "野史": 8.0,
    "干预": 7.0,
    "对话": 6.0,
    "承诺": 6.0,
    "台词": 4.0,
    "关系": 4.0,
    "事件": 2.0,
}

# 核心因子（创伤与执念优先保留）
CORE_FACTORS: set[int] = {
    1,   # 白厄 —— 负世，扛下所有人
    2,   # 昔涟 —— 第一个被命名的因子
    13,  # 德谬歌 —— 容器本身
}

# 来古士（用户）亲自触发的内容额外加权
LAIGUS_FID = 0

# 进入 prompt 的硬上限
PROMPT_MAX_ITEMS = 4
PROMPT_MAX_CHARS = 220
# 只看最近多少轮内的碎片
PROMPT_WINDOW_ROUNDS = 6


@dataclass
class ScoredFragment:
    """带权重的碎片视图。

    Attributes:
        text: 内容。
        kind: 类型。
        fid: 因子序号。
        round_no: 产生轮次。
        weight: 计算出的权重。
        score: 最终排序分（权重 + 时效加成）。
    """

    text: str
    kind: str
    fid: int
    round_no: int
    weight: float
    score: float


def score_fragment(
    kind: str,
    fid: int,
    round_no: int,
    current_round: int,
    text: str,
) -> ScoredFragment:
    """给一条碎片打分。

    Args:
        kind: 碎片类型。
        fid: 因子序号。
        round_no: 产生轮次。
        current_round: 当前轮次。
        text: 内容。

    Returns:
        ScoredFragment: 带权重与排序分的碎片。
    """
    weight = KIND_WEIGHT.get(kind, 1.0)

    # 核心因子的创伤与执念优先
    if fid in CORE_FACTORS and kind in ("创伤", "执念", "牺牲"):
        weight += 3.0

    # 来古士亲自投放的内容必留
    if fid == LAIGUS_FID and kind in ("干预", "对话"):
        weight += 4.0

    # 时效：越近的越容易被想起，衰减很小，避免完全丢掉旧的核心记忆
    age = max(0, current_round - round_no)
    recency = 2.0 / (1.0 + age * 0.15)

    # 过长的条目略微降权，控制 token
    if len(text) > 120:
        weight -= 1.0

    return ScoredFragment(
        text=text,
        kind=kind,
        fid=fid,
        round_no=round_no,
        weight=weight,
        score=weight + recency,
    )


def select_for_prompt(
    candidates: list[ScoredFragment],
    max_items: int = PROMPT_MAX_ITEMS,
    max_chars: int = PROMPT_MAX_CHARS,
) -> list[ScoredFragment]:
    """从候选里挑出能进 prompt 的碎片。

    Args:
        candidates: 已打分的候选碎片。
        max_items: 最多条数。
        max_chars: 最多字符数。

    Returns:
        list[ScoredFragment]: 入选的碎片，按分数从高到低。
    """
    ranked = sorted(candidates, key=lambda x: x.score, reverse=True)
    selected: list[ScoredFragment] = []
    used = 0
    for item in ranked:
        if len(selected) >= max_items:
            break
        cost = len(item.text)
        if used + cost > max_chars and selected:
            continue
        selected.append(item)
        used += cost
    return selected
