"""翁法罗斯模拟的世界状态。

核心机制（与 delta-me13 的永劫回归不同）：
- 每轮 15 分钟强制重置，所有因子回到初始状态——这不是「永劫回归」，只是单纯的归零。
- 但每轮结束会把「记忆碎片」沉淀进 archives：每轮因子都可能多记住一句话、
  多一个执念、多一段关系。
- 下一轮开始时因子带着这些碎片重新开始：从 0 出发，但并非白纸。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .firstcause import FirstCauseState
from .roles import RoleTracker

# 档案容量上限：保证 Demiurge_Archives.json 不会随轮次无限膨胀
ARCHIVE_MAX = 600        # 岁月史书最多保留的碎片条数
CHRONICLE_MAX = 80       # 编年史最多保留的轮次
CHRONICLE_LOG_MAX = 20   # 每轮编年史里最多保留的日志条数


@dataclass
class FactorRuntime:
    """单个因子在一轮内的运行期状态。

    Attributes:
        fid: 因子序号。
        name: 因子名。
        location: 当前所在城邦。
        fire: 是否已取得火种。
        alive: 是否尚未倒下。
        hp: 当前生命。
        max_hp: 生命上限（随轮回层数提升）。
        mood: 当前情绪。
        last_action: 最近一次行动的描述。
    """

    fid: int
    name: str
    location: str = "奥赫玛"
    fire: bool = False
    alive: bool = True
    hp: int = 100
    max_hp: int = 100
    mood: str = "平静"
    last_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化的字典。"""
        return asdict(self)


@dataclass
class Fragment:
    """一条沉淀下来的记忆碎片。

    Attributes:
        fid: 所属因子序号（0 表示全局事件）。
        name: 因子名。
        round_no: 产生的轮次。
        kind: 类型，台词 / 承诺 / 执念 / 关系 / 事件。
        text: 内容。
        ts: 时间戳。
    """

    fid: int
    name: str
    round_no: int
    kind: str
    text: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化的字典。"""
        return asdict(self)


@dataclass
class RoundLog:
    """一轮中的一条日志。

    Attributes:
        round_no: 轮次。
        turn: 轮内序号。
        fid: 相关因子序号（0 表示全局）。
        name: 相关因子名。
        kind: 事件类型。
        text: 内容。
        ts: 时间戳。
    """

    round_no: int
    turn: int
    fid: int
    name: str
    kind: str
    text: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化的字典。"""
        return asdict(self)


class OmphalosState:
    """整个模拟的世界状态。

    Attributes:
        round_no: 当前轮次（从 1 开始）。
        turn: 当前轮内步数。
        running: 是否正在运行。
        started_at: 本轮开始时间戳。
        factors: 因子运行期状态，key 为 fid。
        fragments: 跨轮累积的记忆碎片。
        logs: 当前轮的日志。
        chronicle: 已完成的轮次编年史。
        interventions: 来古士的干预记录。
    """

    def __init__(self, data_dir: Path, round_seconds: int = 900) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # 叙事化命名：这是德谬歌的档案，不是普通的 state 文件
        self.save_path = self.data_dir / "Demiurge_Archives.json"
        # 兼容旧文件名，首次启动时自动迁移
        self._legacy_path = self.data_dir / "omphalos_state.json"
        self.round_seconds = round_seconds

        self.round_no: int = 1
        self.turn: int = 0
        self.running: bool = False
        self.started_at: float = 0.0
        self.factors: dict[int, FactorRuntime] = {}
        self.fragments: list[Fragment] = []
        # 已沉入岁月史书的碎片，不参与 prompt 注入，仅存档
        self.archived_fragments: list[dict[str, Any]] = []
        # 归档时使用的本轮快照，避免读到归零后的数据
        self._fallen_snapshot: list[str] = []
        self._ember_snapshot: int = 0
        self._embers_snapshot: list[str] = []
        self.logs: list[RoundLog] = []
        self.chronicle: list[dict[str, Any]] = []
        self.interventions: list[dict[str, Any]] = []
        # 「生命的第一因」实验层：权杖演算 / 德谬歌成长 / 结局
        self.first_cause = FirstCauseState()
        # 两边身份的行为记录（QQ=开拓者 / WebUI=来古士）
        self.roles = RoleTracker()

    # ---------- 生命周期 ----------

    def reset_round(
        self,
        base_locations: dict[int, str],
        factor_names: dict[int, str],
    ) -> None:
        """开始新一轮，把因子状态归零。

        Args:
            base_locations: 各因子的初始城邦。
            factor_names: 各因子的名字。
        """
        self.turn = 0
        self.logs = []
        self.started_at = time.time()
        self.factors = {}
        self._fallen_snapshot = []
        self._ember_snapshot = 0
        self._embers_snapshot = []
        # 每轮强度随轮次微增，对应「数据一点点保留」的表现
        boost = min(self.round_no - 1, 20)
        for fid, name in factor_names.items():
            self.factors[fid] = FactorRuntime(
                fid=fid,
                name=name,
                location=base_locations.get(fid, "奥赫玛"),
                max_hp=100 + boost * 5,
                hp=100 + boost * 5,
            )

    def remaining_seconds(self) -> int:
        """本轮剩余秒数。"""
        if not self.running or not self.started_at:
            return self.round_seconds
        elapsed = time.time() - self.started_at
        return max(0, int(self.round_seconds - elapsed))

    # ---------- 记录 ----------

    def log(self, fid: int, name: str, kind: str, text: str) -> RoundLog:
        """写入一条本轮日志。

        Args:
            fid: 因子序号，0 表示全局。
            name: 因子名。
            kind: 事件类型。
            text: 内容。

        Returns:
            RoundLog: 写入的日志对象。
        """
        self.turn += 1
        entry = RoundLog(
            round_no=self.round_no,
            turn=self.turn,
            fid=fid,
            name=name,
            kind=kind,
            text=text,
        )
        self.logs.append(entry)
        return entry

    def remember(self, fid: int, name: str, kind: str, text: str) -> Fragment:
        """沉淀一条跨轮记忆碎片。

        Args:
            fid: 因子序号。
            name: 因子名。
            kind: 类型。
            text: 内容。

        Returns:
            Fragment: 写入的碎片。
        """
        frag = Fragment(
            fid=fid,
            name=name,
            round_no=self.round_no,
            kind=kind,
            text=text,
        )
        self.fragments.append(frag)
        if len(self.fragments) > 400:
            self.fragments = self.fragments[-400:]
        return frag

    def sediment_to_archive(self, keep_rounds: int = 6, cap: int = 120) -> int:
        """把过于久远的碎片沉入编年史，不再参与 prompt 注入。

        叙事含义：德谬歌只记得最近的残响，更早的会沉入岁月史书。

        Args:
            keep_rounds: 保留最近多少轮的碎片在活动池中。
            cap: 活动池的硬上限条数。

        Returns:
            int: 本次沉入编年史的条数。
        """
        low = max(0, self.round_no - keep_rounds)
        keep = [f for f in self.fragments if f.round_no >= low]
        drop = [f for f in self.fragments if f.round_no < low]

        # 即使都在窗口内，也按条数上限截断（保留最新的）
        if len(keep) > cap:
            drop.extend(keep[: len(keep) - cap])
            keep = keep[-cap:]

        if not drop:
            return 0

        self.archived_fragments.extend(f.to_dict() for f in drop)
        self.fragments = keep
        # 岁月史书也不会无限长：超出上限时丢最旧的，只保留最近 ARCHIVE_MAX 条
        if len(self.archived_fragments) > ARCHIVE_MAX:
            self.archived_fragments = self.archived_fragments[-ARCHIVE_MAX:]
        return len(drop)

    def close_round(self, summary: str) -> None:
        """结束本轮，把日志归档进编年史。

        Args:
            summary: 本轮的总结。
        """
        self.chronicle.append(
            {
                "round_no": self.round_no,
                "started_at": self.started_at,
                "ended_at": time.time(),
                "turns": self.turn,
                "fallen": list(self._fallen_snapshot),
                "ember_taken": self._ember_snapshot,
                "embers": list(self._embers_snapshot),
                "summary": summary,
                # 只存要点，不存时间戳等冗余字段；日志过多时编年史会撑大文件
                "logs": [
                    {"name": lg.name, "kind": lg.kind, "text": lg.text[:120]}
                    for lg in self.logs[-CHRONICLE_LOG_MAX:]
                ],
            }
        )
        # 编年史有上限，只保留最近 CHRONICLE_MAX 轮
        if len(self.chronicle) > CHRONICLE_MAX:
            self.chronicle = self.chronicle[-CHRONICLE_MAX:]
        self.round_no += 1

    def fragments_for(self, fid: int, limit: int = 8) -> list[Fragment]:
        """取某个因子的记忆碎片。

        Args:
            fid: 因子序号。
            limit: 最多返回条数。

        Returns:
            list[Fragment]: 最近的碎片。
        """
        mine = [f for f in self.fragments if f.fid == fid]
        return mine[-limit:]

    # ---------- 持久化 ----------

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "round_no": self.round_no,
            "turn": self.turn,
            "running": self.running,
            "started_at": self.started_at,
            "factors": {str(k): v.to_dict() for k, v in self.factors.items()},
            "fragments": [f.to_dict() for f in self.fragments],
            "archived_fragments": self.archived_fragments,
            "logs": [lg.to_dict() for lg in self.logs],
            "chronicle": self.chronicle,
            "interventions": self.interventions,
            "first_cause": self.first_cause.to_dict(),
            "roles": self.roles.to_dict(),
            "round_seconds": self.round_seconds,
        }

    def save(self) -> None:
        """原子写入磁盘。

        先写同目录下的临时文件，再用 os.replace 原子替换。
        os.replace 在 Windows 与 POSIX 上都是原子操作，
        即使写入中途崩溃或与下一次写入重叠，也不会留下半截 JSON。
        """
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        tmp = self.save_path.with_suffix(self.save_path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.save_path)

    def load(self) -> bool:
        """从磁盘恢复。

        优先读 Demiurge_Archives.json；若不存在但旧文件在，则迁移过来。

        Returns:
            bool: 是否成功恢复。
        """
        path = self.save_path
        if not path.is_file() and self._legacy_path.is_file():
            path = self._legacy_path
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        self.round_no = int(data.get("round_no", 1))
        self.turn = int(data.get("turn", 0))
        self.running = False
        self.started_at = float(data.get("started_at", 0.0))
        self.round_seconds = int(data.get("round_seconds", self.round_seconds))
        self.factors = {
            int(k): FactorRuntime(**v) for k, v in data.get("factors", {}).items()
        }
        self.fragments = [Fragment(**f) for f in data.get("fragments", [])]
        self.archived_fragments = data.get("archived_fragments", [])
        self.logs = [RoundLog(**lg) for lg in data.get("logs", [])]
        self.chronicle = data.get("chronicle", [])
        self.interventions = data.get("interventions", [])
        fc = data.get("first_cause")
        if isinstance(fc, dict):
            self.first_cause = FirstCauseState.from_dict(fc)
        rd = data.get("roles")
        if isinstance(rd, dict):
            self.roles = RoleTracker.from_dict(rd)
        return True
