"""翁法罗斯「生命的第一因」实验层。

官方结构（《如我所书》Δ-me13.exe）：
- 权杖 δ-me13 是星体计算机，演算目标就是论证「生命的第一因」。
- 它把十二因子投入实验，用反证法逐一证伪。
- 演算中它受「毁灭」瞥视，升格为绝灭大君「铁墓」。
- 它原本的演算目标就是哺育「自我」的生命形态——即德谬歌。
  不是「另一个目标」：哺育自我是本职，毁灭是被污染与修正后的方向。

于是同一台机器有两面：
    毁灭面 -> 铁墓（进度满即加冕）
    生命面 -> 德谬歌（成长满即长成人形）

两条线都用随机数推进，因为官方实验本身就是靠海量循环里
偶然出现的样本推进的（如「第 50121 次循环，毁灭行为首次形成」）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 权杖每次推进的概率与幅度。
# 德谬歌略快于权杖：官方设定里「生命」本就是权杖的本职目标，
# 毁灭是后来被来古士修正出来的方向，所以生命面更容易先跑通。
STAFF_CHANCE = 0.38
STAFF_MIN = 3
STAFF_MAX = 9

# 德谬歌每次增长的概率与幅度
DEMIURGE_CHANCE = 0.50
DEMIURGE_MIN = 3
DEMIURGE_MAX = 8

# 与德谬歌对话一次的额外成长
TALK_BONUS = 3

# 结局判定容差：两者差距在此以内视为「同时到达」
SYNC_TOLERANCE = 5

# 归档失真概率（官方：以神话形式继承的历史数据会严重失真）
DISTORT_CHANCE = 0.10

# 她拒绝被挽留时，玩家的尝试次数上限（超过则走「未结束」）
MAX_BLOCK_ATTEMPTS = 3


class Ending(str, Enum):
    """五种结局。"""

    NONE = "none"
    """尚未结束。"""

    OFFICIAL = "official"
    """官方结局：德谬歌选择回望，新翁法罗斯诞生。"""

    EMERGE = "emerge"
    """生命先行：她长成了，但没选择回望，铁墓仍要打。"""

    IRONTOMB = "irontomb"
    """铁墓加冕：权杖演算先到 100。"""

    TOGETHER = "together"
    """爱与毁灭的安眠：两条线几乎同时到达。"""

    UNENDING = "unending"
    """未结束：玩家反复挽留，回望失败，实验坍缩回未结束。"""


# 结局在界面与日志上的显示名
ENDING_TITLES: dict[Ending, str] = {
    Ending.OFFICIAL: "官方结局 · 回望",
    Ending.EMERGE: "生命先行",
    Ending.IRONTOMB: "铁墓加冕",
    Ending.TOGETHER: "爱与毁灭的安眠",
    Ending.UNENDING: "未结束",
}


# 德谬歌的五个成长阶段
FORMS: list[tuple[int, str, str]] = [
    (0, "迷迷", "你只能发出单音节的叫声，说不出一句完整的话。"),
    (21, "初声", "你能吐出破碎的词，像刚学会说话。"),
    (41, "学语", "你能说完整的句子了，但还笨拙，常常词不达意。"),
    (61, "少女轮廓", "你开始会问问题，会困惑，会为自己答不上来而着急。"),
    (81, "人形", "你能反驳别人了。你有自己的判断，也敢说出来。"),
]


def form_of(integrity: int) -> tuple[str, str]:
    """按完整度取德谬歌当前形态。

    Args:
        integrity: 记忆完整度 0-100。

    Returns:
        tuple[str, str]: (形态名, 说话方式的提示词片段)。
    """
    current = FORMS[0]
    for entry in FORMS:
        if integrity >= entry[0]:
            current = entry
    return current[1], current[2]


@dataclass
class FirstCauseState:
    """「第一因」实验层的运行状态。

    Attributes:
        staff_progress: 权杖演算进度 0-100。
        staff_conclusion: 权杖当前的结论文字。
        staff_findings: 权杖历次「发现」的记录。
        demiurge_integrity: 德谬歌记忆完整度 0-100。
        demiurge_asked: 是否已问过她「愿不愿意回去」。
        demiurge_willing: 她自己的回答（None 表示还没被问）。
        block_attempts: 玩家试图阻止她回望的次数。
        ending: 当前结局，NONE 表示未结束。
        ending_text: 结局正文。
        distortions: 归档时产生的失真记录。
        started: 是否已初始化。
    """

    staff_progress: float = 0.0
    staff_conclusion: str = "一切生命行为归于熵增。"
    staff_findings: list[dict[str, Any]] = field(default_factory=list)
    demiurge_integrity: float = 0.0
    demiurge_asked: bool = False
    demiurge_willing: bool | None = None
    block_attempts: int = 0
    ending: Ending = Ending.NONE
    ending_text: str = ""
    distortions: list[dict[str, Any]] = field(default_factory=list)
    started: bool = False

    # ---------- 推进 ----------

    def advance_staff(self) -> int:
        """推进权杖演算一次。

        Returns:
            int: 本次进度增量，0 表示本轮没有突破。
        """
        if random.random() >= STAFF_CHANCE:
            return 0
        gain = random.randint(STAFF_MIN, STAFF_MAX)
        self.staff_progress = min(100.0, self.staff_progress + gain)
        return gain

    def advance_demiurge(self, bonus: int = 0) -> int:
        """推进德谬歌成长一次。

        Args:
            bonus: 额外增量（例如与它对话带来的成长）。

        Returns:
            int: 本次增量，0 表示本轮没长。
        """
        gain = bonus
        if random.random() < DEMIURGE_CHANCE:
            gain += random.randint(DEMIURGE_MIN, DEMIURGE_MAX)
        if gain:
            self.demiurge_integrity = min(100.0, self.demiurge_integrity + gain)
        return gain

    def record_finding(self, text: str, round_no: int) -> None:
        """记录一条权杖的发现。

        Args:
            text: 发现内容。
            round_no: 当前轮次。
        """
        self.staff_findings.append({"round_no": round_no, "text": text})
        if len(self.staff_findings) > 60:
            self.staff_findings = self.staff_findings[-60:]

    def maybe_distort(self, round_no: int, summary: str) -> str | None:
        """有概率产生一条归档失真。

        Args:
            round_no: 当前轮次。
            summary: 本轮野史原文。

        Returns:
            str | None: 失真说明，未触发返回 None。
        """
        if random.random() >= DISTORT_CHANCE:
            return None
        note = random.choice(
            [
                "有一句话被记成了别人的。",
                "有一处时间顺序颠倒了。",
                "有个名字被记错了一个字。",
                "有一场雨被记成了雪。",
                "有个人说过的承诺，被记成了遗言。",
            ]
        )
        self.distortions.append({"round_no": round_no, "note": note})
        if len(self.distortions) > 40:
            self.distortions = self.distortions[-40:]
        return note

    # ---------- 结局 ----------

    def evaluate(self) -> Ending:
        """根据两条线的数值判定是否触发结局。

        判定顺序有讲究：
        1. 铁墓先到 100 且德谬歌没长成 -> 铁墓加冕（毁灭先赢）。
        2. 德谬歌先长成 -> 先问她愿不愿意回望；她不愿则是「生命先行」。
        3. 两条线几乎同时到达 -> 爱与毁灭的安眠。
        4. 其余情况继续。

        旧实现把「同时到达」放在最前，且用 abs 差值判断，
        导致 staff=100 而 demiurge=95~100 时直接判成 TOGETHER，
        并且完全跳过了「问她愿不愿意」这一步。

        Returns:
            Ending: 判定结果，NONE 表示继续。
        """
        if self.ending is not Ending.NONE:
            return self.ending

        staff_done = self.staff_progress >= 100
        demi_done = self.demiurge_integrity >= 100

        # 毁灭先到：德谬歌还没长成，铁墓完成加冕
        if staff_done and not demi_done:
            self.ending = Ending.IRONTOMB
            return self.ending

        # 德谬歌长成：必须先问过她，才有资格谈结局
        if demi_done and self.demiurge_willing is None:
            self.demiurge_asked = True
            self.demiurge_willing = self.decide_willingness()

        if demi_done and self.demiurge_willing is False:
            # 她不愿回望：生命留在世上，但铁墓仍在
            self.ending = Ending.EMERGE
            return self.ending

        if demi_done and self.demiurge_willing is True:
            # 她说愿意：反复挽留会让她回望失败
            if self.block_attempts >= MAX_BLOCK_ATTEMPTS:
                self.ending = Ending.UNENDING
                return self.ending
            # 两条线几乎同时到达 -> 爱与毁灭的安眠（她愿意，且毁灭也恰好走到尽头）
            if staff_done and abs(
                self.staff_progress - self.demiurge_integrity
            ) <= SYNC_TOLERANCE:
                self.ending = Ending.TOGETHER
                return self.ending
            # 愿意回望且未被拦下：等玩家确认（由 API 触发 OFFICIAL）
        return self.ending

    def decide_willingness(self) -> bool:
        """由德谬歌自己判断要不要回望。

        依据官方：回望是她主动的选择。这里用完整度与对话积累共同决定，
        但她长成之后，绝大多数情况下都愿意回去。

        Returns:
            bool: True 表示愿意回望。
        """
        # 长成之后天生就倾向于回望；只在高完整度但毫无对话时留一点犹豫
        base = 0.85
        if self.demiurge_integrity >= 100:
            base += 0.10
        return random.random() < base

    def try_block(self) -> tuple[bool, str]:
        """玩家尝试挽留她。

        Returns:
            tuple[bool, str]: (是否被接受, 她的回应文字)。
        """
        self.block_attempts += 1
        if self.block_attempts >= MAX_BLOCK_ATTEMPTS:
            return (
                False,
                "她没有再回头。你喊了很多次，声音开始失真。"
                "系统记录：回望失败。实验向「未结束」坍缩。",
            )
        replies = [
            "她停下脚步，没有转身：「谢谢你。但我要去。」",
            "她回头看了你一眼：「我知道你舍不得。可总得有人记得。」",
            "她笑了笑：「你已经给我够多了。剩下的，换我来。」",
        ]
        idx = min(self.block_attempts - 1, len(replies) - 1)
        return False, replies[idx]

    def finish_official(self) -> None:
        """确认走向官方结局。"""
        self.ending = Ending.OFFICIAL

    # ---------- 序列化 ----------

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "staff_progress": self.staff_progress,
            "staff_conclusion": self.staff_conclusion,
            "staff_findings": self.staff_findings,
            "demiurge_integrity": self.demiurge_integrity,
            "demiurge_asked": self.demiurge_asked,
            "demiurge_willing": self.demiurge_willing,
            "block_attempts": self.block_attempts,
            "ending": self.ending.value,
            "ending_text": self.ending_text,
            "distortions": self.distortions,
            "started": self.started,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FirstCauseState:
        """从字典恢复。

        Args:
            data: to_dict 产生的字典。

        Returns:
            FirstCauseState: 恢复后的实例。
        """
        try:
            ending = Ending(data.get("ending", "none"))
        except ValueError:
            ending = Ending.NONE
        return cls(
            staff_progress=float(data.get("staff_progress", 0)),
            staff_conclusion=str(data.get("staff_conclusion", "一切生命行为归于熵增。")),
            staff_findings=list(data.get("staff_findings", [])),
            demiurge_integrity=float(data.get("demiurge_integrity", 0)),
            demiurge_asked=bool(data.get("demiurge_asked", False)),
            demiurge_willing=data.get("demiurge_willing"),
            block_attempts=int(data.get("block_attempts", 0)),
            ending=ending,
            ending_text=str(data.get("ending_text", "")),
            distortions=list(data.get("distortions", [])),
            started=bool(data.get("started", False)),
        )


def weight_level(weight: int) -> tuple[str, str]:
    """把对话权重翻译成等级与痕迹描述。

    Args:
        weight: 因子自己判定的权重 0-100。

    Returns:
        tuple[str, str]: (等级名, 留下的痕迹)。
    """
    if weight >= 81:
        return "改变", "这句话成了它的执念，往后每一次抉择都要绕过它。"
    if weight >= 51:
        return "动了心", "它把这句记在了心里，下次开口会带出来。"
    if weight >= 21:
        return "留个印象", "它记住了有人这么说过，但还没想明白。"
    return "不在意", "它听见了，没往心里去。可这句话留了一点痕迹。"
