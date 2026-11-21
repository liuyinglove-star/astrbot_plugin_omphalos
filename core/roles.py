"""两个身份：QQ 里是开拓者，WebUI 里是来古士。

同一场实验，玩家同时站在两个位置：
- QQ（手机/电脑聊天）-> 开拓者：闯进实验的人，他的话语会污染因子。
- WebUI（插件面板）  -> 来古士：设计实验的人，可以干预、调速、标记异常。

两边的行为都会留下记录，并互相影响。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SideRecord:
    """一条身份行为记录。

    Attributes:
        side: "pioneer"（开拓者）或 "laigus"（来古士）。
        action: 行为类型，如 talk / intervene / speed / mark。
        target: 对象（因子名等）。
        detail: 内容。
        ts: 时间戳。
    """

    side: str
    action: str
    target: str
    detail: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """序列化。"""
        return {
            "side": self.side,
            "action": self.action,
            "target": self.target,
            "detail": self.detail,
            "ts": self.ts,
        }


class RoleTracker:
    """记录两边各做了什么，用于结算与叙事。

    Attributes:
        records: 行为记录。
        pioneer_talks: 开拓者对话次数。
        laigus_acts: 来古士干预次数。
        contamination: 污染度（开拓者的话对因子的影响累积）。
        suppression: 压制度（来古士的干预累积）。
    """

    def __init__(self) -> None:
        self.records: list[SideRecord] = []
        self.pioneer_talks: int = 0
        self.laigus_acts: int = 0
        self.contamination: float = 0.0
        self.suppression: float = 0.0

    def pioneer(self, action: str, target: str, detail: str, weight: int = 0) -> None:
        """记一次开拓者行为。

        Args:
            action: 行为类型。
            target: 对象。
            detail: 内容。
            weight: 该行为的权重（来自因子自己的判定）。
        """
        self.records.append(SideRecord("pioneer", action, target, detail))
        if action == "talk":
            self.pioneer_talks += 1
            self.contamination += max(1.0, weight / 20.0)
        self._trim()

    def laigus(self, action: str, target: str, detail: str, pressure: float = 1.0) -> None:
        """记一次来古士行为。

        Args:
            action: 行为类型。
            target: 对象。
            detail: 内容。
            pressure: 压制强度。
        """
        self.records.append(SideRecord("laigus", action, target, detail))
        self.laigus_acts += 1
        self.suppression += pressure
        self._trim()

    def _trim(self) -> None:
        """限制记录长度。"""
        if len(self.records) > 200:
            self.records = self.records[-200:]

    def balance(self) -> tuple[float, float]:
        """两边的力量对比。

        Returns:
            tuple[float, float]: (污染度, 压制度)。
        """
        return round(self.contamination, 1), round(self.suppression, 1)

    def latest(self, side: str, n: int = 5) -> list[SideRecord]:
        """取某一侧最近的记录。

        Args:
            side: "pioneer" 或 "laigus"。
            n: 条数。

        Returns:
            list[SideRecord]: 最近的记录。
        """
        mine = [r for r in self.records if r.side == side]
        return mine[-n:]

    def to_dict(self) -> dict[str, Any]:
        """序列化。"""
        return {
            "records": [r.to_dict() for r in self.records[-100:]],
            "pioneer_talks": self.pioneer_talks,
            "laigus_acts": self.laigus_acts,
            "contamination": self.contamination,
            "suppression": self.suppression,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleTracker:
        """反序列化。

        Args:
            data: to_dict 的结果。

        Returns:
            RoleTracker: 恢复后的实例。
        """
        t = cls()
        t.pioneer_talks = int(data.get("pioneer_talks", 0))
        t.laigus_acts = int(data.get("laigus_acts", 0))
        t.contamination = float(data.get("contamination", 0))
        t.suppression = float(data.get("suppression", 0))
        for r in data.get("records", []):
            t.records.append(
                SideRecord(
                    side=str(r.get("side", "pioneer")),
                    action=str(r.get("action", "")),
                    target=str(r.get("target", "")),
                    detail=str(r.get("detail", "")),
                    ts=float(r.get("ts", 0)),
                )
            )
        return t
