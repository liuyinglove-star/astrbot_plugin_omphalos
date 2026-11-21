"""翁法罗斯因子模拟 —— AstrBot 插件主入口。

设计要点：
- 每轮 15 分钟（可配置）强制重置，因子回到初始状态。
- 每轮结束由德谬歌归档并续写野史，同时沉淀记忆碎片。
- 下一轮因子带着碎片重新开始：从 0 出发，但并非白纸。
- 用户以来古士身份介入：可对话、可干预、可查询。
"""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .core.brain import OmphalosBrain
from .core.factors import FACTORS, by_fid, by_name
from .core.firstcause import ENDING_TITLES, Ending, form_of, weight_level
from .core.voice import CyreneVoice
from .core import voice as voice_module
from .core.journey import (
    FATAL_PATHS,
    HERO_BY_PATH,
    KHARSLANNA_PROMPT,
    Phase,
    RoundRuntime,
    make_seeds,
)
from .core.state import OmphalosState
from .webapi import OmphalosWebApi


@register(
    "astrbot_plugin_omphalos",
    "林墨",
    "翁法罗斯因子模拟：以德谬歌为容器、十三位因子为实验体的轮回推演",
    "v1.1.0",
    "https://github.com/Rorical/delta-me13",
)
class OmphalosPlugin(Star):
    """翁法罗斯模拟插件。"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        round_minutes = int(self.config.get("round_minutes", 15))
        self.round_seconds = max(60, round_minutes * 60)

        data_dir = Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_omphalos"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.state = OmphalosState(data_dir, round_seconds=self.round_seconds)
        self.state.load()

        self.brain = OmphalosBrain(
            context,
            self.state,
            provider_id=str(self.config.get("provider_id", "")).strip(),
        )
        # 昔涟音色（唯一内嵌的语音，其他角色模型太大不做）
        # 参考音频与模型权重都由用户配置，未配置时自动降级为纯文字。
        voice_module.configure(
            ref_root=str(self.config.get("cyrene_ref_root", "")).strip(),
            gpt_weights=str(self.config.get("cyrene_gpt_weights", "")).strip(),
            sovits_weights=str(self.config.get("cyrene_sovits_weights", "")).strip(),
        )
        self.cyrene_voice = CyreneVoice(
            enabled=bool(self.config.get("cyrene_voice", True))
        )
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        # 写入锁与推演锁分离：指令处理与后台循环都会写盘，
        # 用同一把锁会把慢速磁盘写阻塞决策，分开后各管各的。
        self._save_lock = asyncio.Lock()
        self.round_rt = RoundRuntime()
        self.seeds: dict[str, str] = {}

    async def _save(self) -> None:
        """加锁写盘。

        所有写盘都走这里，避免后台推演与指令处理并发覆盖同一个文件。
        真正的原子性由 OmphalosState.save 的临时文件 + os.replace 保证。
        """
        async with self._save_lock:
            try:
                self.state.save()
            except OSError as exc:
                logger.error(f"[omphalos] 写入德谬歌档案失败: {exc}")

    # ---------- 生命周期 ----------

    async def initialize(self) -> None:
        """插件加载时自动恢复并启动模拟。"""
        logger.info(
            f"[omphalos] 已加载，当前第 {self.state.round_no} 轮，"
            f"累积碎片 {len(self.state.fragments)} 条"
        )
        self._register_web_apis()
        if self.config.get("auto_start", True):
            await self._start_loop()

    def _register_web_apis(self) -> None:
        """注册 WebUI 控制台需要的全部接口。"""
        api = OmphalosWebApi(self)
        routes = [
            ("status", api.get_status, ["GET"], "获取翁法罗斯全局状态"),
            ("logs", api.get_logs, ["GET"], "获取最近日志"),
            ("chronicle", api.get_chronicle, ["GET"], "获取编年史"),
            ("archive", api.get_archive, ["GET"], "获取记忆残响"),
            ("starmap", api.get_starmap, ["GET"], "获取意识海记忆星图"),
            ("start", api.post_start, ["POST"], "启动推演"),
            ("stop", api.post_stop, ["POST"], "暂停推演"),
            ("reset", api.post_reset, ["POST"], "强制进入下一轮"),
            ("talk", api.post_talk, ["POST"], "与因子对话"),
            ("kharslanna", api.post_kharslanna, ["POST"], "与卡厄斯兰那对话"),
            ("intervene", api.post_intervene, ["POST"], "投放干预"),
            ("export", api.post_export, ["POST"], "导出编年史"),
            ("first_cause", api.get_first_cause, ["GET"], "获取第一因实验状态"),
            ("first_cause_talk", api.post_first_cause_talk, ["POST"], "与德谬歌对话"),
            ("first_cause_block", api.post_block, ["POST"], "挽留德谬歌"),
            ("first_cause_confirm", api.post_confirm, ["POST"], "确认回望"),
            ("first_cause_reset", api.post_first_cause_reset, ["POST"], "重开实验层"),
            ("roles", api.get_roles, ["GET"], "获取双身份行为统计"),
            ("mark", api.post_mark, ["POST"], "来古士标记因子异常"),
            ("epilogue", api.get_epilogue, ["GET"], "获取结局彩蛋"),
        ]
        for name, handler, methods, desc in routes:
            self.context.register_web_api(
                f"/astrbot_plugin_omphalos/{name}", handler, methods, desc
            )
        logger.info(f"[omphalos] 已注册 {len(routes)} 个 Web API")

    async def terminate(self) -> None:
        """插件卸载时停止循环并保存。"""
        await self._stop_loop()
        logger.info("[omphalos] 已停止并保存状态")

    # ---------- 循环 ----------

    async def _start_loop(self) -> None:
        """启动模拟循环。"""
        if self._task and not self._task.done():
            return
        self._stop = asyncio.Event()
        self.state.running = True
        if not self.state.factors:
            self._reset_round()
        await self._save()
        self._task = asyncio.create_task(self._run_loop())

    async def _stop_loop(self) -> None:
        """停止模拟循环并保存。

        stop 的所有入口（指令 / Web API / 卸载）都走这里，保证
        _stop 事件、running 标记和后台任务三者状态一致，
        否则重新 start 会留下一个还在跑、却已无人引用的旧任务。
        """
        self._stop.set()
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.state.running = False
        await self._save()

    async def _run_loop(self) -> None:
        """主循环：持续推演，到点重置。

        启动时先等待一段时间，让 AstrBot 完成 provider 加载，
        否则第一次决策会因为取不到模型而空转。
        """
        try:
            # 等待 provider 就绪，最多 90 秒
            ready = False
            for _ in range(18):
                if self._stop.is_set():
                    return
                if self.brain._get_provider() is not None:
                    ready = True
                    break
                await asyncio.sleep(5)
            if not ready:
                logger.warning(
                    "[omphalos] 等待 90 秒仍没有可用的模型，"
                    "推演会继续但每一步都会因取不到模型而空转，请检查 provider 配置"
                )
            logger.info("[omphalos] 模型已就绪，开始推演")

            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._tick(), timeout=120)
                except asyncio.TimeoutError:
                    logger.error("[omphalos] 单步决策超时，跳过")
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"[omphalos] 单步异常: {exc}", exc_info=True)
                await self._save()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=20)
                    break
                except asyncio.TimeoutError:
                    pass
                if self.state.remaining_seconds() <= 0:
                    await self._end_round()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[omphalos] 循环异常: {exc}", exc_info=True)

    def _reset_round(self) -> None:
        """开始新一轮，因子归零，重新打乱逐火顺序。"""
        self.state.reset_round(
            base_locations={f.fid: f.home or "奥赫玛" for f in FACTORS},
            factor_names={f.fid: f.name for f in FACTORS},
        )
        self.round_rt = RoundRuntime()
        self.round_rt.shuffle_order()
        self.seeds = make_seeds()
        logger.info(
            f"[omphalos] 第 {self.state.round_no} 轮开始，"
            f"逐火顺序: {' → '.join(self.round_rt.order)}"
        )

    async def _tick(self) -> None:
        """推进一个阶段。

        阶段流程：出发 → 逐火（逐个权柄）→ 盗火行者 → 归档。
        每个 tick 推进一个权柄，中间可以穿插事件与对话。
        """
        async with self._lock:
            rt = self.round_rt
            round_no = self.state.round_no

            # 阶段 0：出发
            if rt.phase == Phase.IDLE:
                rt.shuffle_order()
                rt.phase = Phase.JOURNEY
                for path in rt.order:
                    hero = HERO_BY_PATH[path]
                    code = self.seeds.get(path, "")[:6]
                    self.state.log(
                        0, "权杖δ-me13", "出发",
                        f"黄金裔「{hero}」`{code}`踏上追逐「{path}」的逐火之旅。",
                    )
                self.state.log(
                    0, "权杖δ-me13", "纪元",
                    f"—— 第 {round_no} 轮逐火之旅开始 ——",
                )
                return

            # 阶段 1：逐火
            if rt.phase == Phase.JOURNEY:
                path = rt.next_path()
                if path is None:
                    rt.phase = Phase.THIEF
                    return

                hero = HERO_BY_PATH[path]
                factor = next((f for f in FACTORS if f.name == hero), None)

                if path in FATAL_PATHS:
                    rt.fallen.append(hero)
                    if factor:
                        self.state.factors[factor.fid].alive = False
                        self.state.factors[factor.fid].fire = True
                    self.state.log(
                        factor.fid if factor else 0, hero, "牺牲",
                        f"{hero}为保全翁法罗斯的「{path}」牺牲在了逐火之旅的途中。",
                    )
                    self.state.remember(
                        factor.fid if factor else 0, hero, "牺牲",
                        f"「{path}」的火种，是用{hero}的命换的。",
                    )
                else:
                    if factor:
                        self.state.factors[factor.fid].fire = True
                    self.state.log(
                        factor.fid if factor else 0, hero, "夺火",
                        f"{hero}通过「{path}」的试炼，代替泰坦执掌了翁法罗斯「{path}」的权柄。",
                    )

                # 卡厄斯兰那吞纳火种
                rt.ember_taken += 1
                rt.embers.append(path)
                # 记录完整的权柄序列，避免后一枚的累计数把前一枚覆盖掉
                seq = "、".join(f"「{p}」" for p in rt.embers)
                self.state.log(
                    0, "卡厄斯兰那", "吞火",
                    f"「{path}」之火种被卡厄斯兰那收于己身。"
                    f"本轮已吞 {rt.ember_taken} 枚：{seq}。",
                )

                # 随机事件
                evt = rt.roll_event(path)
                if evt:
                    self.state.log(0, "【事件】", "事件", evt)
                    self.state.remember(0, "翁法罗斯", "事件", evt)

                # 让该权柄的黄金裔说一句话（走模型）
                if factor is not None:
                    result = await self.brain.factor_action(factor)
                    speech = str(result.get("speech", "")).strip()
                    if speech:
                        self.state.log(factor.fid, hero, "台词", f"「{speech}」")
                        if len(speech) >= 10:
                            self.state.remember(factor.fid, hero, "台词", speech)
                return

            # 阶段 2：盗火行者闯入
            if rt.phase == Phase.THIEF:
                self.state.log(
                    0, "权杖δ-me13", "异变",
                    "—— 盗火行者闯入了创世涡心！！！ ——",
                )
                self.state.log(
                    0, "卡厄斯兰那", "收割",
                    "卡厄斯兰那跨过所有倒下的身影，把余下的火种一枚枚收进自己烧穿的胸腔。",
                )
                rt.phase = Phase.ARCHIVE
                return

            # 阶段 3：归档
            if rt.phase == Phase.ARCHIVE:
                rt.phase = Phase.IDLE
                await self._end_round()

    async def _end_round(self) -> None:
        """结束本轮：总结、德谬歌归档、重置。"""
        # 必须在 _reset_round 之前快照本轮数据，否则归档会读到归零后的计数。
        rt = self.round_rt
        round_no = self.state.round_no
        ember_taken = rt.ember_taken
        embers = list(rt.embers)
        fallen = list(rt.fallen)
        # 写进 state，供 close_round 归档使用（reset_round 会清空 rt）
        self.state._fallen_snapshot = fallen
        self.state._ember_snapshot = ember_taken
        self.state._embers_snapshot = embers

        # 给德谬歌的素材：优先保留台词与牺牲，而不是统计数字
        speeches = [
            f"{lg.name}说：「{lg.text.strip('「」')}」"
            for lg in self.state.logs
            if lg.kind == "台词" and lg.text
        ]
        deaths = [
            f"{lg.name}倒下了。{lg.text}"
            for lg in self.state.logs
            if lg.kind == "牺牲"
        ]
        events = [lg.text for lg in self.state.logs if lg.kind == "事件"]
        # 夺火只保留"谁通过了哪条路径"，吞火合并成一行，避免重复的累计序列
        gained = [
            lg.text for lg in self.state.logs if lg.kind == "夺火"
        ]

        parts = [f"第 {round_no} 轮。"]

        if speeches:
            parts.append("这一轮里，有人说过这些话：")
            parts.extend(f"  - {s}" for s in speeches[-12:])

        if deaths:
            parts.append("有人没能走完：")
            parts.extend(f"  - {d}" for d in deaths)

        if gained:
            parts.append("有人通过了试炼：")
            parts.extend(f"  - {g}" for g in gained[-10:])

        if events:
            parts.append("沿途的见闻：")
            parts.extend(f"  - {e}" for e in events[-6:])

        if embers:
            parts.append(
                f"最终，{ember_taken} 枚火种依次落进卡厄斯兰那手里："
                f"{'、'.join(f'「{p}」' for p in embers)}。"
            )
        context = "\n".join(parts)
        summary = await self.brain.demiurge_archive(context)
        if summary:
            self.state.remember(13, "德谬歌", "野史", summary)
            self.state.log(13, "德谬歌", "归档", summary)
            # 归档失真：官方设定里以神话形式继承的历史会严重失真
            note = self.state.first_cause.maybe_distort(round_no, summary)
            if note:
                self.state.log(0, "权杖δ-me13", "失真", f"记录失真：{note}")

        self.state.close_round(summary or "（本轮无记录）")

        # 德谬歌的选择性记忆：久远的碎片沉入岁月史书，不再进入 prompt
        sedimented = self.state.sediment_to_archive(
            keep_rounds=int(self.config.get("memory_rounds", 6)),
            cap=int(self.config.get("memory_cap", 120)),
        )
        if sedimented:
            logger.info(f"[omphalos] {sedimented} 条残响沉入岁月史书")

        self._reset_round()
        await self._save()
        logger.info(f"[omphalos] 第 {self.state.round_no - 1} 轮结束，已归档并重置")

        # 实验层推进放在最后：归档完成后再推动两条线
        await self._advance_first_cause(context)

    async def _advance_first_cause(self, round_context: str) -> None:
        """推进「第一因」实验层，并检查是否触发结局。

        Args:
            round_context: 本轮世界摘要，用于生成权杖的发现。
        """
        fc = self.state.first_cause
        if not fc.started:
            fc.started = True
        if fc.ending is not Ending.NONE:
            return

        # 权杖：随机突破时，让模型写一条实验记录
        gain = fc.advance_staff()
        if gain:
            text = await self.brain.staff_finding(round_context, fc.staff_progress)
            if text:
                fc.record_finding(text, self.state.round_no - 1)
                self.state.log(0, "权杖δ-me13", "演算", text)
            logger.info(f"[omphalos] 权杖演算 +{gain}，当前 {fc.staff_progress:.0f}%")

        # 德谬歌：记忆增长
        demi_gain = fc.advance_demiurge()
        if demi_gain:
            old_form = form_of(int(fc.demiurge_integrity - demi_gain))[0]
            new_form = form_of(int(fc.demiurge_integrity))[0]
            if old_form != new_form:
                self.state.log(
                    13, "德谬歌", "蜕变",
                    f"德谬歌长到了「{new_form}」。",
                )
                logger.info(f"[omphalos] 德谬歌进入「{new_form}」")
            logger.info(
                f"[omphalos] 德谬歌成长 +{demi_gain}，当前 {fc.demiurge_integrity:.0f}%"
            )

        # 判定是否触发结局
        ending = fc.evaluate()
        if ending is not Ending.NONE:
            await self._trigger_ending(ending, round_context)

    async def _trigger_ending(self, ending: Ending, context: str) -> None:
        """结算一个结局。

        Args:
            ending: 结局类型。
            context: 世界摘要。
        """
        fc = self.state.first_cause
        fc.ending = ending
        text = await self.brain.ending_text(ending.value, context)
        fc.ending_text = text
        self.state.log(
            0, "权杖δ-me13", "结局", f"【{ENDING_TITLES[ending]}】{text}"
        )
        logger.info(f"[omphalos] 结局触发：{ending.value}")
        await self._save()

    # ---------- 工具方法 ----------

    def _status_text(self) -> str:
        """生成状态文本。"""
        remain = self.state.remaining_seconds()
        alive = sum(1 for rt in self.state.factors.values() if rt.alive)
        fired = sum(1 for rt in self.state.factors.values() if rt.fire)
        rt = self.round_rt
        phase_names = {
            Phase.IDLE: "待出发",
            Phase.JOURNEY: "逐火中",
            Phase.THIEF: "盗火行者闯入",
            Phase.ARCHIVE: "归档中",
        }
        lines = [
            f"【翁法罗斯 · 第 {self.state.round_no} 轮】",
            f"阶段：{phase_names.get(rt.phase, '?')}　"
            f"逐火进度：{rt.cursor}/{len(rt.order) or 12}",
            f"运行中：{'是' if self.state.running else '否'}　"
            f"剩余：{remain // 60}分{remain % 60}秒",
            f"因子存活：{alive}/13　已持火种：{fired}　"
            f"卡厄斯兰那吞纳：{rt.ember_taken}",
            f"记忆碎片：{len(self.state.fragments)} 条　"
            f"已完成轮次：{len(self.state.chronicle)}",
        ]
        if rt.embers:
            lines.append(f"已吞权柄：{'、'.join(rt.embers)}")
        if rt.fallen:
            lines.append(f"本轮倒下：{'、'.join(rt.fallen)}")
        if rt.events:
            lines.append(f"本轮事件：{rt.events[-1]}")
        if self.state.logs:
            lines.append("")
            lines.append("最近动态：")
            for lg in self.state.logs[-5:]:
                lines.append(f"  {lg.name}：{lg.text[:44]}")
        return "\n".join(lines)

    def _factors_text(self) -> str:
        """生成因子列表文本。"""
        lines = ["【十三位因子】"]
        for f in FACTORS:
            rt = self.state.factors.get(f.fid)
            loc = rt.location if rt else f.home
            fire = "🔥" if (rt and rt.fire) else ""
            demi = "（容器）" if f.is_demiurge else ""
            lines.append(
                f"{f.fid}. {f.name}{fire}{demi} ← {f.path} / {f.prime_drive}"
                f"　@{loc}"
            )
        return "\n".join(lines)

    # ---------- 指令 ----------

    @filter.command("omphalos")
    async def omphalos_cmd(self, event: AstrMessageEvent):
        """翁法罗斯模拟主指令。

        指令参数由框架按空格切分后无法确定分配，因此只接 event，
        自己从去掉指令名后的整段文本里拆「子命令 + 余下内容」。

        Args:
            event: 消息事件。
        """
        raw = event.message_str.strip()
        if raw.startswith("/"):
            raw = raw[1:]
        parts = raw.split(maxsplit=1)
        rest = parts[1].strip() if len(parts) > 1 else ""
        # 第二个词是子命令，但 talk 的目标名可能带「·」（丹恒·腾荒），
        # 只用空白切分，不再按其他字符切
        if rest:
            head = rest.split(maxsplit=1)
            sub = head[0].lower()
            arg = head[1].strip() if len(head) > 1 else ""
        else:
            sub, arg = "", ""

        if sub in ("", "status"):
            yield event.plain_result(self._status_text())
            return

        if sub == "start":
            await self._start_loop()
            yield event.plain_result(
                f"模拟已启动。第 {self.state.round_no} 轮，{self.round_seconds // 60} 分钟一轮。"
            )
            return

        if sub == "stop":
            await self._stop_loop()
            yield event.plain_result("模拟已暂停，状态已保存。")
            return

        if sub == "factors":
            yield event.plain_result(self._factors_text())
            return

        if sub == "records":
            if not self.state.chronicle:
                yield event.plain_result("还没有完成的轮次。")
                return
            recent = self.state.chronicle[-3:]
            out = []
            for c in recent:
                out.append(f"【第 {c['round_no']} 轮 · {c['turns']} 步】")
                out.append(c.get("summary", "（无记录）"))
                out.append("")
            yield event.plain_result("\n".join(out).strip())
            return

        if sub == "talk":
            parts = arg.split(maxsplit=1) if arg else []
            if len(parts) < 2:
                yield event.plain_result("用法：/omphalos talk <因子名或序号> <你想说的话>")
                return
            target, message = parts[0], parts[1]
            factor = by_name(target)
            if factor is None:
                yield event.plain_result(f"找不到因子「{target}」。可用 /omphalos factors 查看。")
                return
            reply = await self.brain.factor_reply(factor, message)
            # 让因子自己判断这句话对它有多深的影响，而不是给一个固定权重
            weight, thought = await self.brain.factor_weigh(factor, message, reply)
            level, trace = weight_level(weight)
            self.state.log(
                factor.fid, factor.name,
                "开拓者",
                f"开拓者：{message} → {factor.name}：{reply}",
            )
            self.state.remember(
                factor.fid, factor.name, "对话",
                f"开拓者说「{message}」，我答「{reply}」（{level}：{thought}）",
            )
            # 权重足够高时，这句话会凝成一个执念，跨轮留下来
            if weight >= 81:
                self.state.remember(factor.fid, factor.name, "执念", thought)
            # QQ 侧的行为记在开拓者名下
            self.state.roles.pioneer("talk", factor.name, message, weight=weight)
            await self._save()
            yield event.plain_result(
                f"【{factor.name}】\n{reply}\n\n—— {trace}"
            )
            return

        if sub == "intervene":
            text = (arg or "").strip()
            if not text:
                yield event.plain_result("用法：/omphalos intervene <你想投放的话>")
                return
            self.state.interventions.append(
                {"round_no": self.state.round_no, "text": text, "ts": time.time()}
            )
            # 干预会作为碎片注入全局，影响后续决策
            self.state.remember(0, "来古士", "干预", text)
            self.state.log(0, "来古士", "干预", text)
            await self._save()
            yield event.plain_result(
                f"已向来古士投放干预。它会以「变量」的形式进入部分因子的记忆。\n> {text}"
            )
            return

        if sub in ("archive", "archives"):
            frs = self.state.fragments
            arc = self.state.archived_fragments
            by_kind: dict[str, int] = {}
            for f in frs:
                by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
            lines = [
                "【德谬歌的档案】",
                "",
                f"仍在残响中：{len(frs)} 条（参与 prompt）",
                f"已沉入史书：{len(arc)} 条（不再参与 prompt）",
                f"编年史：{len(self.state.chronicle)} 轮",
            ]
            if by_kind:
                lines.append("")
                lines.append("残响构成：" + "、".join(f"{k}{v}" for k, v in by_kind.items()))
            recent = frs[-5:]
            if recent:
                lines.append("")
                lines.append("最近记得的：")
                for f in recent:
                    lines.append(f"  ({f.kind}) {f.name}：{f.text[:40]}")
            yield event.plain_result("\n".join(lines))
            return

        if sub == "export":
            if not self.state.chronicle:
                yield event.plain_result("还没有可导出的编年史。")
                return
            lines = ["# 翁法罗斯编年史", ""]
            for c in self.state.chronicle:
                lines.append(f"## 第 {c['round_no']} 轮")
                lines.append("")
                lines.append(c.get("summary", "（无记录）"))
                lines.append("")
            out_path = self.state.data_dir / "omphalos_chronicle.md"
            out_path.write_text("\n".join(lines), encoding="utf-8")
            yield event.plain_result(f"已导出编年史：{out_path}")
            return

        if sub == "kharslanna":
            text = (arg or "").strip()
            if not text:
                yield event.plain_result("用法：/omphalos kharslanna <你想对他说的话>")
                return
            reply = await self.brain.raw_chat(KHARSLANNA_PROMPT, text)
            self.state.log(
                0, "卡厄斯兰那", "对话",
                f"来古士：{text} → 卡厄斯兰那：{reply}",
            )
            self.state.remember(0, "卡厄斯兰那", "对话", f"来古士对我说「{text}」，我回「{reply}」")
            await self._save()
            yield event.plain_result(f"【卡厄斯兰那】\n{reply}")
            return

        yield event.plain_result(
            "用法：/omphalos [start|stop|status|factors|talk|intervene|kharslanna|records|export]"
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """普通消息入口：私聊里与德谬歌的快捷对话。

        这是「开拓者」这一侧：他说的话会作为变量污染因子。
        默认关闭且仅管理员生效——否则私聊里每一句闲聊都会被德谬歌吞掉，
        其他插件与 LLM 流程都拿不到这条消息。

        Args:
            event: 消息事件。
        """
        if not self.config.get("private_talk", False):
            return
        text = (event.message_str or "").strip()
        if not text or text.startswith("/"):
            return
        # 不在群里抢话，只处理私聊
        if not event.is_private_chat():
            return
        if not event.is_admin():
            return
        if not self.state.running:
            return
        # QQ 侧就是开拓者：他的话会污染因子
        reply = await self.brain.demiurge_speak(text)
        self.state.log(13, "德谬歌", "对话", f"开拓者：{text} → {reply}")
        self.state.roles.pioneer("talk", "德谬歌", text, weight=40)
        await self._save()
        yield event.plain_result(reply)
