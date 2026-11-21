"""翁法罗斯控制台的 Web API。

路由前缀统一为 /astrbot_plugin_omphalos，前端在 pages/console/ 下调用。
"""

from __future__ import annotations

import time
from typing import Any

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from .core.factors import FACTORS
from .core.firstcause import (
    ENDING_TITLES,
    TALK_BONUS,
    Ending,
    FirstCauseState,
    form_of,
    weight_level,
)
from .core.journey import KHARSLANNA_PROMPT, Phase
from .core.memory_filter import KIND_WEIGHT
from .core.state import ARCHIVE_MAX, CHRONICLE_MAX
from .core.starmap import build_star_map
from .core.wishes import pick_voice_line, select_wishes


class OmphalosWebApi:
    """把插件状态暴露成 Web API。

    Attributes:
        plugin: 持有游戏状态的插件实例。
    """

    def __init__(self, plugin: Any) -> None:
        """初始化。

        Args:
            plugin: OmphalosPlugin 实例。
        """
        self.plugin = plugin

    # ---------- 读接口 ----------

    async def get_status(self) -> Any:
        """返回完整状态快照，供前端一次渲染。

        Returns:
            JSONResponse: 状态数据。
        """
        plugin = self.plugin
        st = plugin.state
        rt = plugin.round_rt
        remain = st.remaining_seconds()

        phase_names = {
            Phase.IDLE: "待出发",
            Phase.JOURNEY: "逐火中",
            Phase.THIEF: "盗火行者闯入",
            Phase.ARCHIVE: "归档中",
        }

        factors = []
        for f in FACTORS:
            frt = st.factors.get(f.fid)
            factors.append(
                {
                    "fid": f.fid,
                    "name": f.name,
                    "code": f.code,
                    "path": f.path,
                    "prime_drive": f.prime_drive,
                    "home": f.home,
                    "is_demiurge": f.is_demiurge,
                    "alive": frt.alive if frt else True,
                    "fire": frt.fire if frt else False,
                    "hp": frt.hp if frt else 0,
                    "max_hp": frt.max_hp if frt else 0,
                    "location": frt.location if frt else f.home,
                }
            )

        return json_response(
            {
                "round_no": st.round_no,
                "turn": st.turn,
                "running": st.running,
                "phase": phase_names.get(rt.phase, "?"),
                "phase_code": int(rt.phase),
                "progress": {"cursor": rt.cursor, "total": len(rt.order) or 12},
                "remaining_seconds": remain,
                "round_seconds": st.round_seconds,
                "order": rt.order,
                "fallen": rt.fallen,
                "ember_taken": rt.ember_taken,
                "embers": rt.embers,
                "events": rt.events[-5:],
                "factors": factors,
                "fragment_count": len(st.fragments),
                "archived_count": len(st.archived_fragments),
                "chronicle_count": len(st.chronicle),
                "limits": {
                    "archive_max": ARCHIVE_MAX,
                    "chronicle_max": CHRONICLE_MAX,
                },
                "recent_logs": [
                    {"name": lg.name, "kind": lg.kind, "text": lg.text}
                    for lg in st.logs[-20:]
                ],
            }
        )

    async def get_logs(self) -> Any:
        """返回最近日志。

        Returns:
            JSONResponse: 日志列表。
        """
        limit = int(request.query.get("limit", "50") or 50)
        logs = self.plugin.state.logs[-limit:]
        return json_response(
            {
                "logs": [
                    {
                        "turn": lg.turn,
                        "name": lg.name,
                        "kind": lg.kind,
                        "text": lg.text,
                    }
                    for lg in logs
                ],
            }
        )

    async def get_chronicle(self) -> Any:
        """返回编年史。

        Returns:
            JSONResponse: 各轮野史。
        """
        limit = int(request.query.get("limit", "20") or 20)
        records = self.plugin.state.chronicle[-limit:]
        return json_response(
            {
                "chronicle": [
                    {
                        "round_no": c.get("round_no"),
                        "turns": c.get("turns"),
                        "summary": c.get("summary", ""),
                        "fallen": c.get("fallen", []),
                        "ember_taken": c.get("ember_taken", 0),
                        "embers": c.get("embers", []),
                    }
                    for c in records
                ],
            }
        )

    async def get_starmap(self) -> Any:
        """返回意识海记忆星图数据。

        把归档里的碎片与轮次总结映射成带坐标的星点，供前端渲染。

        Returns:
            JSONResponse: stars / stats。
        """
        st = self.plugin.state
        try:
            # 注意：st.fragments 是 Fragment 对象，st.archived_fragments 是
            # dict（归档时调用 f.to_dict()）。这里统一转成 dict 再往下传。
            def to_payload(f: Any) -> dict[str, Any]:
                """把 Fragment 或 dict 统一成纯字典。

                Args:
                    f: Fragment 实例或已序列化的 dict。

                Returns:
                    dict[str, Any]: 含 fid/name/kind/text/round_no/ts 的字典。
                """
                if isinstance(f, dict):
                    return {
                        "fid": f.get("fid", 0),
                        "name": f.get("name", ""),
                        "kind": f.get("kind", ""),
                        "text": f.get("text", ""),
                        "round_no": f.get("round_no", 0),
                        "ts": f.get("ts", 0.0),
                    }
                return {
                    "fid": f.fid,
                    "name": f.name,
                    "kind": f.kind,
                    "text": f.text,
                    "round_no": f.round_no,
                    "ts": f.ts,
                }

            payload: dict[str, Any] = {
                "round_no": st.round_no,
                "fragments": [to_payload(f) for f in st.fragments],
                "archived_fragments": [to_payload(f) for f in st.archived_fragments],
                "chronicle": [
                    {
                        "round_no": c.get("round_no", 0),
                        "started_at": c.get("started_at", 0),
                        "summary": c.get("summary", ""),
                    }
                    for c in st.chronicle
                ],
            }
            return json_response(build_star_map(payload))
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[omphalos] starmap 构建失败: {exc}", exc_info=True)
            return error_response(f"星图构建失败: {type(exc).__name__}: {exc}")

    async def get_archive(self) -> Any:
        """返回残响统计。

        Returns:
            JSONResponse: 活动碎片与史书。
        """
        st = self.plugin.state
        by_kind: dict[str, int] = {}
        for f in st.fragments:
            by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        return json_response(
            {
                "active": [
                    {
                        "fid": f.fid,
                        "name": f.name,
                        "kind": f.kind,
                        "text": f.text,
                        "round_no": f.round_no,
                    }
                    for f in st.fragments[-60:]
                ],
                "by_kind": by_kind,
                "weights": KIND_WEIGHT,
                "archived_count": len(st.archived_fragments),
            }
        )

    # ---------- 第一因实验层 ----------

    async def get_first_cause(self) -> Any:
        """返回「生命的第一因」实验层状态。

        Returns:
            JSONResponse: 双线进度、形态、结局。
        """
        fc = self.plugin.state.first_cause
        form_name, form_hint = form_of(int(fc.demiurge_integrity))
        return json_response(
            {
                "started": fc.started,
                "staff": {
                    "progress": round(fc.staff_progress, 1),
                    "conclusion": fc.staff_conclusion,
                    "findings": fc.staff_findings[-12:],
                },
                "demiurge": {
                    "integrity": round(fc.demiurge_integrity, 1),
                    "form": form_name,
                    "form_hint": form_hint,
                    "willing": fc.demiurge_willing,
                    "asked": fc.demiurge_asked,
                },
                "ending": fc.ending.value,
                "ending_title": ENDING_TITLES.get(fc.ending, ""),
                "ending_text": fc.ending_text,
                "block_attempts": fc.block_attempts,
                "distortions": fc.distortions[-8:],
            }
        )

    async def post_first_cause_talk(self) -> Any:
        """与德谬歌对话（按当前形态）。

        Returns:
            JSONResponse: 她的回应、形态、成长增量。
        """
        payload = await request.json(default={})
        message = str(payload.get("message", "")).strip()
        if not message:
            return error_response("缺少消息内容")

        fc = self.plugin.state.first_cause
        form_name, form_hint = form_of(int(fc.demiurge_integrity))
        try:
            reply = await self.plugin.brain.demiurge_in_form(
                form_name, form_hint, message
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[omphalos] 与德谬歌对话失败: {exc}")
            return error_response(f"对话失败: {exc}")

        # 与它说话本身就会让它成长
        gained = fc.advance_demiurge(bonus=TALK_BONUS)
        self.plugin.state.log(
            13, "德谬歌", "对话", f"开拓者：{message} → 德谬歌：{reply}"
        )
        self.plugin.state.remember(
            13, "德谬歌", "对话", f"开拓者说「{message}」，我答「{reply}」"
        )
        ending = fc.evaluate()
        if ending is not Ending.NONE:
            await self.plugin._trigger_ending(ending, f"玩家与德谬歌的对话：{message}")
        await self.plugin._save()

        form_after, _ = form_of(int(fc.demiurge_integrity))
        return json_response(
            {
                "reply": reply,
                "form": form_after,
                "integrity": round(fc.demiurge_integrity, 1),
                "gained": gained,
            }
        )

    async def post_block(self) -> Any:
        """尝试挽留德谬歌。

        Returns:
            JSONResponse: 她的回应与当前结局。
        """
        fc = self.plugin.state.first_cause
        if not fc.demiurge_asked:
            return error_response("她还没有做出选择。")
        accepted, words = fc.try_block()
        self.plugin.state.log(0, "开拓者", "挽留", words)
        ending = fc.evaluate()
        if ending is not Ending.NONE:
            await self.plugin._trigger_ending(ending, words)
        await self.plugin._save()
        return json_response(
            {
                "accepted": accepted,
                "words": words,
                "attempts": fc.block_attempts,
                "ending": fc.ending.value,
            }
        )

    async def post_confirm(self) -> Any:
        """确认让德谬歌回望，走向官方结局。

        走向官方结局的前提是她自己愿意回望（evaluate 已问过她），
        这里只负责让她把最后的话说出来并结算。

        Returns:
            JSONResponse: 结局。
        """
        fc = self.plugin.state.first_cause
        if not fc.demiurge_asked:
            return error_response("她还没有做出选择。")
        if not fc.demiurge_willing:
            return error_response("她不愿回望，这条路走不通。")
        st = self.plugin.state
        memory = "\n".join(f.text for f in st.fragments_for(13, 12)) or "她记得的所有事"
        _, words = await self.plugin.brain.demiurge_willingness(memory)
        fc.finish_official()
        await self.plugin._trigger_ending(
            Ending.OFFICIAL, f"她最后的回应：{words}"
        )
        return json_response(
            {"ending": fc.ending.value, "words": words, "text": fc.ending_text}
        )

    async def post_first_cause_reset(self) -> Any:
        """重开实验层（不动世界本体）。

        Returns:
            JSONResponse: 操作结果。
        """
        self.plugin.state.first_cause = FirstCauseState()
        await self.plugin._save()
        return json_response({"message": "实验层已重置，两条线归零"})

    # ---------- 双身份：来古士侧 ----------

    async def get_roles(self) -> Any:
        """返回两个身份的行为统计（来古士面板用）。

        同时给出因子对管理员的当前敌意阶段，让玩家看见态度在恶化。

        Returns:
            JSONResponse: 污染度、压制度、敌意阶段与最近记录。
        """
        rt = self.plugin.state.roles
        contamination, suppression = rt.balance()

        # 敌意阶段与 brain 里的判断保持同一套阈值。
        # 注意措辞：因子敌视的对象是「他正在毁灭这个世界」这件事，
        # 不是「他是管理员」这个身份，所以标签落在「对抗」而非笼统的「恨」。
        done = self.plugin.state.round_no
        if done <= 6:
            stage, label = 0, "未察觉"
        elif done <= 20:
            stage, label = 1, "起疑"
        elif done <= 40:
            stage, label = 2, "正面对抗"
        else:
            stage, label = 3, "决战"

        return json_response(
            {
                "pioneer_talks": rt.pioneer_talks,
                "laigus_acts": rt.laigus_acts,
                "contamination": contamination,
                "suppression": suppression,
                "hostility_stage": stage,
                "hostility_label": label,
                "pioneer_recent": [r.to_dict() for r in rt.latest("pioneer", 6)],
                "laigus_recent": [r.to_dict() for r in rt.latest("laigus", 6)],
            }
        )

    async def post_mark(self) -> Any:
        """来古士标记某个因子为「异常」（只影响叙事，不直接改数值）。

        Returns:
            JSONResponse: 操作结果。
        """
        payload = await request.json(default={})
        fid = int(payload.get("fid", 0) or 0)
        reason = str(payload.get("reason", "")).strip() or "表现出不稳定的自主倾向"
        factor = next((f for f in FACTORS if f.fid == fid), None)
        if factor is None:
            return error_response("找不到该因子")
        st = self.plugin.state
        st.roles.laigus("mark", factor.name, reason, pressure=1.5)
        st.log(0, "来古士", "标记", f"将 {factor.name} 标记为异常：{reason}")
        st.remember(0, "来古士", "干预", f"管理员将「{factor.name}」标记为异常。")
        await self.plugin._save()
        return json_response({"message": f"已标记 {factor.name}"})

    # ---------- 结局彩蛋 ----------

    def _context_tags(self) -> set[str]:
        """从本局真实发生的事里收集情节标签，供祝福随机抽取使用。

        Returns:
            set[str]: 情节标签集合。
        """
        st = self.plugin.state
        tags: set[str] = set()
        text_all = " ".join(lg.text for lg in st.logs)
        chronicle_text = " ".join(
            str(c.get("summary", "")) for c in st.chronicle[-20:]
        )
        blob = text_all + " " + chronicle_text

        # 牺牲
        fallen = self.plugin.round_rt.fallen
        if fallen or "牺牲" in blob:
            tags.add("有人牺牲")
        for name in ("风堇", "遐蝶", "丹恒·腾荒", "阿格莱雅", "白厄"):
            if name in fallen or f"{name}为保全" in blob:
                tags.add(f"{name}牺牲")

        # 各角色的代表性表现
        if "一个人扛" in blob:
            tags.add("白厄独扛")
        if "恨" in blob:
            tags.add("白厄憎恨")
        if "明天见" in blob:
            tags.add("缇宝明天见")
        if "王" in blob or "戴冠" in blob:
            tags.add("万敌称王")
        if "织" in blob or "金线" in blob:
            tags.add("浪漫节制")
        if "灵魂" in blob or "理性" in blob:
            tags.add("理性诘问")
        if "照顾自己" in blob or "休息" in blob:
            tags.add("风堇叮嘱")
        if "谎" in blob or "骗" in blob:
            tags.add("诡计谎言")
        if "律" in blob or "凯撒" in blob:
            tags.add("律法")
        if "剑旗" in blob or "歌" in blob:
            tags.add("海瑟音")
        if "磐岩" in blob or "大地" in blob:
            tags.add("大地")
        if "麦田" in blob:
            tags.add("麦田")
        if st.round_no > 10:
            tags.add("永劫回归")

        # 玩家两侧的参与
        if st.roles.pioneer_talks >= 3:
            tags.add("开拓者出力")
        return tags

    async def get_epilogue(self) -> Any:
        """返回结局彩蛋数据：十二祝福 + 昔涟语音。

        每次调用都会按本局经历重新随机抽取，所以同名结局的祝词不一样。

        Returns:
            JSONResponse: 祝福列表与语音 base64。
        """
        fc = self.plugin.state.first_cause
        if fc.ending is Ending.NONE:
            return error_response("实验尚未结束")

        tags = self._context_tags()
        wishes = select_wishes(context_tags=tags)
        voice_line = pick_voice_line()

        audio = None
        if fc.ending is Ending.OFFICIAL:
            audio = await self.plugin.cyrene_voice.synth(
                voice_line, emotion="温柔", speed=0.92
            )

        return json_response(
            {
                "ending": fc.ending.value,
                "ending_title": ENDING_TITLES.get(fc.ending, ""),
                "ending_text": fc.ending_text,
                "wishes": [
                    {
                        "name": w.name,
                        "path": w.path,
                        "text": w.text,
                        "turn_to_player": w.turn_to_player,
                    }
                    for w in wishes
                ],
                "context_tags": sorted(tags),
                "cyrene_line": voice_line,
                "cyrene_audio": audio,
            }
        )


    async def post_start(self) -> Any:
        """启动模拟。

        Returns:
            JSONResponse: 操作结果。
        """
        await self.plugin._start_loop()
        await self.plugin._save()
        return json_response({"message": "已启动推演"})

    async def post_stop(self) -> Any:
        """暂停模拟。

        Returns:
            JSONResponse: 操作结果。
        """
        await self.plugin._stop_loop()
        return json_response({"message": "已暂停"})

    async def post_reset(self) -> Any:
        """强制开始新一轮。

        Returns:
            JSONResponse: 操作结果。
        """
        plugin = self.plugin
        async with plugin._lock:
            # 走完整归档（含德谬歌野史、记忆沉淀与第一因推进），
            # 否则「下一轮」会让本轮对实验层完全不起作用
            await plugin._end_round()
        await plugin._save()
        return json_response(
            {"message": f"已进入第 {plugin.state.round_no} 轮"}
        )

    async def post_talk(self) -> Any:
        """与某个因子对话。

        Returns:
            JSONResponse: 因子的回答。
        """
        payload = await request.json(default={})
        fid = int(payload.get("fid", 0) or 0)
        message = str(payload.get("message", "")).strip()
        if not fid or not message:
            return error_response("缺少因子或消息内容")

        factor = next((f for f in FACTORS if f.fid == fid), None)
        if factor is None:
            return error_response(f"找不到序号为 {fid} 的因子")

        try:
            reply = await self.plugin.brain.factor_reply(factor, message)
            weight, thought = await self.plugin.brain.factor_weigh(
                factor, message, reply
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[omphalos] 对话失败: {exc}")
            return error_response(f"对话失败: {exc}")

        level, trace = weight_level(weight)
        self.plugin.state.log(
            factor.fid, factor.name,
            "来古士",
            f"来古士：{message} → {factor.name}：{reply}",
        )
        self.plugin.state.remember(
            factor.fid, factor.name, "对话",
            f"来古士说「{message}」，我答「{reply}」（{level}：{thought}）",
        )
        if weight >= 81:
            self.plugin.state.remember(factor.fid, factor.name, "执念", thought)
        st = self.plugin.state
        st.roles.laigus("talk", factor.name, message, pressure=max(1.0, weight / 20.0))
        await self.plugin._save()
        return json_response(
            {
                "name": factor.name,
                "reply": reply,
                "weight": weight,
                "level": level,
                "trace": trace,
            }
        )

    async def post_kharslanna(self) -> Any:
        """与卡厄斯兰那对话。

        Returns:
            JSONResponse: 回答。
        """
        payload = await request.json(default={})
        message = str(payload.get("message", "")).strip()
        if not message:
            return error_response("缺少消息内容")

        try:
            reply = await self.plugin.brain.raw_chat(KHARSLANNA_PROMPT, message)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[omphalos] 卡厄斯兰那对话失败: {exc}")
            return error_response(f"对话失败: {exc}")
        self.plugin.state.log(
            0, "卡厄斯兰那", "对话", f"来古士：{message} → 卡厄斯兰那：{reply}"
        )
        await self.plugin._save()
        return json_response({"name": "卡厄斯兰那", "reply": reply})

    async def post_intervene(self) -> Any:
        """作为来古士投放干预。

        Returns:
            JSONResponse: 操作结果。
        """
        payload = await request.json(default={})
        text = str(payload.get("text", "")).strip()
        if not text:
            return error_response("缺少干预内容")
        st = self.plugin.state
        st.interventions.append(
            {"round_no": st.round_no, "text": text, "ts": time.time()}
        )
        st.remember(0, "来古士", "干预", text)
        st.log(0, "来古士", "干预", text)
        await self.plugin._save()
        return json_response({"message": "干预已投放，它将成为因子们的变量"})

    async def post_export(self) -> Any:
        """导出编年史 Markdown 并返回文本。

        Returns:
            JSONResponse: Markdown 文本。
        """
        st = self.plugin.state
        lines = ["# 翁法罗斯编年史", ""]
        for c in st.chronicle:
            lines.append(f"## 第 {c.get('round_no')} 轮")
            lines.append("")
            if c.get("fallen"):
                lines.append(f"倒下：{'、'.join(c['fallen'])}")
                lines.append("")
            if c.get("embers"):
                n = c.get("ember_taken", len(c["embers"]))
                lines.append(f"吞纳 {n} 枚火种：{'、'.join(c['embers'])}")
                lines.append("")
            lines.append(c.get("summary", "（无记录）"))
            lines.append("")
        text = "\n".join(lines)
        out = st.data_dir / "omphalos_chronicle.md"
        out.write_text(text, encoding="utf-8")
        return json_response({"markdown": text, "path": str(out)})
