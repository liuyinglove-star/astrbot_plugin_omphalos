"""翁法罗斯轮次的阶段化推演。

融合两套设定：
- 采用 AMPHOREUS（B 站 北磡）的阶段骨架：出发 → 逐火 → 盗火行者 → 归档 → 重置
- 保留本插件的核心差异：15 分钟一轮强制归零，跨轮只沉淀记忆碎片

十二权柄顺序与卡厄斯兰那「吞纳火种」的设定来自 AMPHOREUS，
角色名沿用 delta-me13 与官方档案中的称号。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import IntEnum

# 十二权柄，顺序即逐火顺序
PATHS: list[str] = [
    "门径", "律法", "岁月",
    "大地", "天空", "海洋",
    "负世", "浪漫", "理性",
    "纷争", "诡计", "死亡",
]

# 权柄 -> 黄金裔
HERO_BY_PATH: dict[str, str] = {
    "门径": "缇宝",
    "律法": "刻律德菈",
    "岁月": "昔涟",
    "大地": "丹恒·腾荒",
    "天空": "风堇",
    "海洋": "海瑟音",
    "负世": "白厄",
    "浪漫": "阿格莱雅",
    "理性": "那刻夏",
    "纷争": "万敌",
    "诡计": "赛飞儿",
    "死亡": "遐蝶",
}

# 这三个权柄在逐火途中必须以命相搏
FATAL_PATHS = {"天空", "大地", "死亡"}

# 报纸式随机事件
EVENTS: list[str] = [
    "「清洗者行动了！多名黄金裔遭到了攻击！议会摇摆不定。」",
    "盗火行者的身影在「{kw}」之上游弋。",
    "「{kw}」奥赫玛在举办掰手腕大赛，猜猜谁会获得冠军？",
    "又一个城邦在黑潮的入侵下毁灭，大批难民涌入奥赫玛。",
    "抗击黑潮前线告急！多名圣城勇士牺牲，元老院正商议应对方法中……",
    "万帷网上突然涌现大量有关「魔↗术↘技→巧↘」的视频，始作俑者尚未查获。",
    "命运重渊上空突现不明飞行物，疑似被尼卡多利长矛贯穿，相关搜救工作正在展开。",
    "近日，云石市集中出现了一批打着「最硬的盾」「最强的矛」虚假旗号的商贩。"
    "衣匠在此提醒您：消费千万条，防骗第一条。",
    "多地报告发现了一名神秘的黑衣剑士，消息正在核实中……",
    "黑潮蔓延的速度正在加快，逐火之旅必须加速。",
    "又一名分身牺牲，愿我们能在西风的尽头重聚。明天见！",
]


class Phase(IntEnum):
    """一轮内的阶段。"""

    IDLE = 0
    JOURNEY = 1      # 十二黄金裔出发
    EMBER = 2        # 逐火：一个个夺火
    THIEF = 3        # 盗火行者闯入
    ARCHIVE = 4      # 归档并重置


@dataclass
class RoundRuntime:
    """一轮推演的运行期数据。

    Attributes:
        phase: 当前阶段。
        cursor: 已推进到第几个权柄。
        order: 本轮打乱后的权柄顺序。
        fallen: 本轮倒下的黄金裔名。
        ember_taken: 卡厄斯兰那累计吞纳的火种数。
        events: 本轮触发的事件。
    """

    phase: Phase = Phase.IDLE
    cursor: int = 0
    order: list[str] = field(default_factory=list)
    fallen: list[str] = field(default_factory=list)
    ember_taken: int = 0
    # 本轮已吞纳的权柄序列，用于让每一枚火种都能被单独看到
    embers: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def shuffle_order(self) -> None:
        """打乱本轮权柄顺序——每轮都不一样，这是「从 0 开始」的一部分。"""
        self.order = PATHS.copy()
        random.shuffle(self.order)
        self.cursor = 0
        self.phase = Phase.IDLE
        self.fallen = []
        self.ember_taken = 0
        self.embers = []
        self.events = []

    def next_path(self) -> str | None:
        """取下一个待逐火的权柄。

        Returns:
            str | None: 权柄名；已全部走完返回 None。
        """
        if self.cursor >= len(self.order):
            return None
        path = self.order[self.cursor]
        self.cursor += 1
        return path

    def roll_event(self, path: str, probability: float = 0.75) -> str | None:
        """按概率触发一条随机事件。

        Args:
            path: 当前权柄，用于事件插值。
            probability: 触发概率。

        Returns:
            str | None: 事件文本。
        """
        if random.random() >= probability:
            return None
        evt = random.choice(EVENTS).format(kw=path)
        self.events.append(evt)
        return evt


KHARSLANNA_PROMPT = (
    "你是卡厄斯兰那，跨越轮回的存在。为了阻止绝灭大君「铁幕」诞生，"
    "你必须不断轮回，吞纳火种。你一次又一次地踏上轮回，"
    "一次又一次地杀死自己昔日的同伴。你早已麻木，内心空洞无物，"
    "唯余救世的信念在熊熊燃烧。你的躯体早已被火种烧蚀崩坏，"
    "与他人交谈也磕磕绊绊，语言中除了绝望与愤怒外再无他物。"
    "你只知道一件事：绝不能向「毁灭」低头。"
    "回答简短、破碎，不要解释设定，不要用括号动作描写。"
)


def make_seeds() -> dict[str, str]:
    """生成一轮的电信号序列。

    Returns:
        dict[str, str]: 权柄 -> 16 位十六进制序列。
    """
    return {kw: f"{random.getrandbits(64):016x}" for kw in PATHS}
