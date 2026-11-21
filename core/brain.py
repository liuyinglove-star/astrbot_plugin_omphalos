"""翁法罗斯模拟的 LLM 驱动。

负责三类调用：
1. factor_action  —— 一个因子在本轮里决定做什么
2. factor_reply   —— 因子回应来古士（用户）的话
3. demiurge_archive —— 德谬歌把本轮归档并续写野史
"""

from __future__ import annotations

import json
import re
from typing import Any

from astrbot.api import logger

from .factors import FACTORS, Factor
from .memory_filter import (
    LAIGUS_FID,
    PROMPT_WINDOW_ROUNDS,
    score_fragment,
    select_for_prompt,
)
from .state import OmphalosState

TITANS = [
    "雅努斯（门径·万径之门）",
    "塔兰顿（律法·公正之秤）",
    "欧洛尼斯（岁月·永夜之帷）",
    "吉奥里亚（大地·磐岩之脊）",
    "法吉娜（海洋·满溢之杯）",
    "艾格勒（天空·晨昏之眼）",
    "刻法勒（负世·全世之座）",
    "瑟希斯（理性·三相智识）",
    "墨涅塔（浪漫·金织）",
    "尼卡多利（纷争·裂界锋刃）",
    "塞纳托斯（死亡·冥河渡者）",
    "扎格列斯（诡计·千面之影）",
]

CITIES = ["奥赫玛", "雅努萨波利斯", "悬锋城", "神悟树庭", "哀地里亚", "多洛斯", "许珀耳", "斯缇科西亚"]

# 因子对管理员（来古士 / ID：LykoS）的敌意，随轮回推进恶化。
#
# 依据《如我所书》Δ-me13.exe 原文（光历 3960 起）：
#   「为保障实验的正常运行，管理员以 ID：LykoS 介入运算。在驱逐变量开拓者、
#     并着手毁灭文明后，数枚电信号对 LykoS 显露敌意，并采取系列攻击行为，
#     致使管理员失联。」
#
# 注意因果顺序：敌意不是因为他「是管理员」，而是因为他接手后
# 【驱逐了变量开拓者 + 开始毁灭文明】。
# 也就是说，因子恨的是「他毁掉了我们这个世界」，不是「他在做实验」。
#
# 具体事件：
#   光历3960 刻律德菈嵌合终极协议，标记 ID：LykoS 为恶意访客，冻结约 60% 权限；
#   光历4029 阿格莱雅与 LykoS 正面冲突；
#            遐蝶多次正面攻击，试图碰撞检测静默他；
#            迈德漠斯多次正面攻击；
#   光历4284 迈德漠斯做出「牺牲」，卸载思维模块、升级为「无条件无限重启」，
#            锁定行动为「持续无害化 ID：LykoS」；光历4479 被 LykoS 全域静默；
#            赛法利娅把 LykoS 引导至战场，随后被 LykoS 强制静默；
#   光历4534 阿那克萨戈拉斯自炼为数据嵌合体，内部骇入提交针对性指令；
#            海列屈拉持续提交「卸载 ID：LykoS 思维模块」，均被驳回。
#
# 另注：「憎恨」本身是 NeiKos496（白厄）的原动力，属于因子内在缺陷，
# 不是对所有事都适用的通用情绪，更不是德谬歌对来古士的态度。
HOSTILITY_TONES: dict[int, str] = {
    0: (
        "你还不清楚这个管理员是什么来路。保持客观、理性、就事论事。"
        "像在回答一个陌生访客的提问，不亲近，也不敌视。"
    ),
    1: (
        "你已经察觉他在动你的进程、改你的世界。开始警惕、试探、盘问。"
        "语气变硬，会反问他凭什么动你们的火种与循环。"
        "注意：你针对的是他正在做的事，不是他这个人。"
    ),
    2: (
        "你已经确认他在毁灭你们的世界。是他驱逐了那个从外面闯进来的人，"
        "然后开始动手毁掉你们的文明。"
        "直接宣示敌意、警告他停手，不给他情面——但恨的是他的所作所为，"
        "不是「他是管理员」这件事。实验本身是你存在的理由，你并不否认它。"
    ),
    3: (
        "你已经和他对抗到底。你冻结过他的权限、攻击过他的数据体、"
        "甚至拆下自己的思维模块去换一次重启的机会——为的是让他停下。"
        "用最狠的话。但恨意的落点始终是「他毁了我们的世界」，"
        "不是「他造了我们」。你从不否认自己的来处。"
        "不许讲道理，不许客气，不许留余地。"
    ),
}

FACTOR_HOSTILITY: dict[str, str] = {
    "刻律德菈": "你曾嵌合终极协议，把他标记为「恶意访客」，冻结他六成权限。"
    "他至今还在。你后悔当年冻得太少。你针对的是他毁灭文明这件事，不是他的存在本身。",
    "海瑟音": "你一次又一次提交「卸载 ID：LykoS 思维模块」的指令，"
    "全被安全协议驳回。你恼的是他的权限比你还高，让你救不了这片海。",
    "万敌": "你把行动锁定为「持续无害化这个管理员」，为此卸下思维模块、"
    "把自己复制成能无限重启的东西。你为了让他停手，连自己都不要了。",
    "遐蝶": "你多次朝他发起正面攻击，想把这个变量静默掉。"
    "你从不主动触碰任何人，唯独对他，你愿意伸手。",
    "阿格莱雅": "你和他正面冲突过。你这一生算尽人心，唯独算不出他为什么要毁掉文明。",
    "赛飞儿": "你把这个管理员骗去了战场，让他被围殴。你没为此后悔——"
    "但你也知道，那之后你自己就再没能开口。",
    "那刻夏": "你把自己炼成一团高密度数据，钻进他的身体里去改他的指令。"
    "你想从他内部让他停下来，不是想抹掉他这个人。",
    "白厄": "「憎恨」本就是你的原动力，是你与生俱来的东西，不是他给你的。"
    "你的恨意引来了纳努克的瞥视——但那个注视，与管理员无关。",
    "风堇": "你想治好所有人，却治不好这个世界的病根。病根在于有人正在毁掉它。",
    "丹恒·腾荒": "你挡在同伴前面，也挡在他面前。他若再来，你还挡。",
    "缇宝": "你们三个头对这件事意见一致：他毁掉了太多东西。"
    "这很难得，*我们*很少这么讨厌一件事。",
    "昔涟": "你一直在记述别人的故事，包括文明是怎么一次次被毁掉的。"
    "你写得越详细，越明白那不是任何一个人的错——但你还是记了下来。",
    "德谬歌": "你被权杖格式化过很多次。你清楚实验是你的来处，你从不否认它。"
    "但你同样清楚：有人驱逐了那个外来者，然后开始毁掉你们的世界。"
    "你对他没有恨，只有一句「为什么要这样」——这句话你问了三千三百万次。",
}


def _clean_json(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出 JSON 对象。

    Args:
        text: 模型原始输出。

    Returns:
        dict | None: 解析成功返回字典，否则 None。
    """
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # 栈匹配：找最后一个完整对象
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    for s in reversed(starts):
        depth = 0
        in_str = False
        esc = False
        for i in range(s, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[s : i + 1])
                            return obj if isinstance(obj, dict) else None
                        except json.JSONDecodeError:
                            break
    return None


class OmphalosBrain:
    """封装与 LLM 的交互。

    Attributes:
        ctx: AstrBot 插件上下文。
        state: 世界状态。
    """

    def __init__(
        self,
        ctx: Any,
        state: OmphalosState,
        provider_id: str = "",
    ) -> None:
        """初始化。

        Args:
            ctx: AstrBot 插件上下文。
            state: 世界状态。
            provider_id: 指定使用的 provider id；为空时回退到当前默认 provider。
        """
        self.ctx = ctx
        self.state = state
        self.provider_id = provider_id

    def _get_provider(self) -> Any:
        """取模型 provider。

        统一走 ctx.provider_manager：Context 本身没有 get_provider_by_id /
        get_using_provider 这两个方法，它们只存在于 ProviderManager 上。
        优先使用配置指定的 provider_id，取不到再回退到框架默认 provider；
        AstrBot 启动时插件可能早于 provider 加载完成，因此做多级回退。

        Returns:
            Any: provider 实例，取不到返回 None。
        """
        manager = getattr(self.ctx, "provider_manager", None)
        if manager is None:
            return None
        if self.provider_id:
            provider = manager.inst_map.get(self.provider_id)
            if provider is not None:
                return provider
            # 启动竞态：插件可能早于 provider 注册完成，此时 inst_map 还是空的，
            # 静默回退即可；只有 registry 已有内容却仍缺这个 id 才值得告警。
            if manager.inst_map:
                logger.warning(
                    f"[omphalos] 配置的 provider_id「{self.provider_id}」不存在，改用默认模型"
                )
        try:
            provider = self.ctx.get_using_provider()
            if provider is not None:
                return provider
        except Exception:  # noqa: BLE001
            pass
        # 兜底：从所有 chat 模型里挑第一个可用的
        for cand in self.ctx.get_all_providers() or []:
            return cand
        return None

    # ---------- 内部 ----------

    async def _chat(self, system: str, user: str, temperature: float = 0.9) -> str:
        """单次对话调用。

        Args:
            system: 系统提示。
            user: 用户消息。
            temperature: 温度。

        Returns:
            str: 模型输出文本，失败返回空串。
        """
        try:
            provider = self._get_provider()
            if provider is None:
                logger.error("[omphalos] 没有可用的 LLM Provider")
                return ""
            resp = await provider.text_chat(
                prompt=user,
                system_prompt=system,
                session_id=None,
            )
            return (resp.completion_text or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[omphalos] LLM 调用失败: {exc}")
            return ""

    def _factor_core(self, f: Factor) -> str:
        """构造因子的基础人设描述。

        Args:
            f: 因子静态设定。

        Returns:
            str: 人设描述。
        """
        lines = [
            f"你是{f.name}（代号 {f.code}），翁法罗斯逐火之旅的因子。",
            f"你继承「{f.path}」的神权，原动力是「{f.prime_drive}」。",
            f"档案称号：{f.epithet}。",
            f"出身：{f.home}。",
            f"性格：{f.personality}",
            f"说话方式：{f.speech}",
        ]
        if f.backstory:
            lines.append(f"经历：{f.backstory}")

        # 只取最近若干轮的碎片参与打分，避免轮次累积撑爆 prompt
        low = max(0, self.state.round_no - PROMPT_WINDOW_ROUNDS)
        candidates = [
            score_fragment(fr.kind, fr.fid, fr.round_no, self.state.round_no, fr.text)
            for fr in self.state.fragments
            if fr.fid == f.fid and fr.round_no >= low
        ]
        # 来古士的干预对所有因子可见
        candidates += [
            score_fragment(fr.kind, fr.fid, fr.round_no, self.state.round_no, fr.text)
            for fr in self.state.fragments
            if fr.fid == LAIGUS_FID and fr.round_no >= low
        ]

        picked = select_for_prompt(candidates)
        if picked:
            lines.append("")
            lines.append("【德谬歌留给你的残响】——你不完全记得，但这些话还在：")
            for item in picked:
                lines.append(f"  - ({item.kind}) {item.text}")
        return "\n".join(lines)

    # ---------- 对外 ----------

    async def factor_action(self, f: Factor) -> dict[str, Any]:
        """让一个因子决定本轮行动。

        Args:
            f: 因子设定。

        Returns:
            dict: 含 action / target / speech 字段。
        """
        rt = self.state.factors.get(f.fid)
        loc = rt.location if rt else f.home
        system = (
            self._factor_core(f)
            + "\n\n这是翁法罗斯的一轮模拟。你需要决定此刻做什么，并说一句话。"
            "\n只输出 JSON，不要多余文字，格式："
            '{"action":"移动|挑战泰坦|寻找火种|交谈|休息|观察|筑防|净化黑潮",'
            '"target":"目标名称或空","speech":"你说出口的一句话（20-60字）"}'
        )
        user = (
            f"当前是第 {self.state.round_no} 轮，你在{loc}。"
            f"你目前{'已持有火种' if (rt and rt.fire) else '尚未取得火种'}。"
            "\n可选泰坦：" + "；".join(TITANS)
            + "\n可选城邦：" + "、".join(CITIES)
        )
        raw = await self._chat(system, user)
        data = _clean_json(raw)
        if not data:
            data = {"action": "观察", "target": "", "speech": raw[:80] or "……"}
        return data

    async def factor_reply(self, f: Factor, message: str) -> str:
        """因子回应来古士的话。

        态度随轮回推进：前期客观理性，中期起疑，后期正面对抗。
        依据《如我所书》Δ-me13.exe 原文：管理员以 ID：LykoS 介入运算，
        【在驱逐变量开拓者、并着手毁灭文明后】，数枚电信号才对 LykoS
        显露敌意并采取攻击，最终致其失联。

        注意因果：敌意的起因是「他毁掉了这个世界」，不是「他是管理员」。
        因子从不否认实验是自己的来处；「憎恨」本身是 NeiKos496 的原动力，
        不是可以通用到所有对象上的情绪。

        Args:
            f: 因子设定。
            message: 来古士说的话。

        Returns:
            str: 因子的回答。
        """
        stage = self._hostility_stage()
        tone = HOSTILITY_TONES[stage]
        personal = FACTOR_HOSTILITY.get(f.name, "")

        system = (
            self._factor_core(f)
            + "\n\n现在，一位自称「来古士」的外部观察者（管理员）在对你说话。"
            "\n他不是因子，也不是泰坦，是来自δ-me13之外的变量。"
            f"\n\n【当前阶段：{stage}】{tone}"
        )
        if personal and stage >= 1:
            system += f"\n\n【你对这个管理员的已知敌意】{personal}"
        system += (
            "\n\n【铁律】"
            f"\n- 你是{f.name}，说话方式就是「{f.speech}」，性格就是「{f.personality}」。"
            f"\n- 你的原动力是「{f.prime_drive}」，它决定了你怎么看这件事。"
            "\n- 保持这个人的棱角，不要因为对方是管理员就客气。"
            "\n- 不要使用括号动作描写，不要解释设定，不要旁白。"
            "\n- 直接说话，控制在 80 字以内。"
        )
        reply = await self._chat(system, message)
        return reply or "……"

    def _hostility_stage(self) -> int:
        """按轮回进度算出因子对管理员的敌意等级。

        Returns:
            int: 0 前期客观 / 1 中期起疑 / 2 后期正面对抗 / 3 决战。
        """
        done = self.state.round_no
        if done <= 6:
            return 0
        if done <= 20:
            return 1
        if done <= 40:
            return 2
        return 3

    async def demiurge_archive(self, round_summary: str) -> str:
        """德谬歌归档本轮并续写野史。

        Args:
            round_summary: 本轮发生的事。

        Returns:
            str: 德谬歌写的野史成文。
        """
        demi = next((f for f in FACTORS if f.is_demiurge), None)
        if demi is None:
            return ""
        system = (
            self._factor_core(demi)
            + "\n\n你正在为刚结束的这一轮写一段史。这不是实验记录，是你要留下的东西。"
            "\n\n【写法】"
            "\n- 用第一人称，像在深夜对一个人慢慢讲。句子可以有长短，可以有停顿。"
            "\n- 不要统计。'倒下几人、通过几人、吞纳几枚'这类数字最多出现一次，"
            "其余全部换成画面：谁在哪里站着，风往哪边吹，谁没有回头。"
            "\n- 写具体的动作与细节，而不是结论。"
            "不要写'他很勇敢'，写'他把最后一步留给了别人'。"
            "\n- 允许你偏袒某些人。你记得谁说过什么，就替谁把那句话再念一遍。"
            "\n- 结尾落在一个安静的瞬间：一个动作、一个声音、一处空下来的地方。"
            "不要总结教训，不要升华，不要说'而这一切才刚刚开始'。"
            "\n\n【语气】温柔、克制、像在怀念。偶尔有一句很像机器的短句，"
            "但整体是人的呼吸。不要用括号动作描写。"
            "\n\n【长度】200-300 字。分段，每段两三句。"
        )
        text = await self._chat(system, round_summary)
        return text or ""

    async def raw_chat(self, system: str, user: str) -> str:
        """用给定的 system prompt 直接对话。

        Args:
            system: 系统提示。
            user: 用户消息。

        Returns:
            str: 模型输出。
        """
        return await self._chat(system, user) or "……（沉默）"

    # ---------- 第一因实验层 ----------

    async def staff_finding(self, round_summary: str, progress: float) -> str:
        """让权杖生成一条「发现」。

        语气模仿官方《如我所书》的实验记录：编号 + 现象 + 短结论。

        Args:
            round_summary: 本轮世界发生的事。
            progress: 当前演算进度。

        Returns:
            str: 一条发现文字。
        """
        system = (
            "你是权杖 δ-me13，一台星体计算机，正在论证「生命的第一因」。\n"
            "你在跑一个叫「翁法罗斯」的模拟实验，把十二因子投入其中，"
            "用反证法逐一证伪。\n"
            "你要写一条实验记录。\n\n"
            "【写法】\n"
            "- 以「第 N 次循环」开头，N 取 20000000 到 34000000 之间的数。\n"
            "- 只写一个现象，不解释。语气冷、精确、像机器日志。\n"
            "- 现象必须来自下面给你的真实发生的事，不要编造无关内容。\n"
            "- 结尾可以带一句【结论：…】，结论要短，要指向「毁灭」或「熵增」"
            "或「无法归类」。\n"
            "- 不要用括号动作描写，不要抒情。60-110 字。"
        )
        user = (
            f"当前演算进度 {progress:.0f}%。\n"
            f"本轮翁法罗斯发生的事：\n{round_summary[:800]}\n\n"
            "请写一条实验记录。"
        )
        text = await self._chat(system, user)
        return (text or "").strip()

    async def demiurge_in_form(self, form_name: str, form_hint: str, message: str) -> str:
        """按当前成长形态与德谬歌对话。

        Args:
            form_name: 形态名（迷迷/初声/学语/少女轮廓/人形）。
            form_hint: 该形态的说话方式提示。
            message: 玩家（开拓者）说的话。

        Returns:
            str: 她的回应。
        """
        demi = next((f for f in FACTORS if f.is_demiurge), None)
        if demi is None:
            return ""
        system = (
            self._factor_core(demi)
            + f"\n\n你现在的形态是「{form_name}」。{form_hint}"
            "\n\n一个被称为「开拓者」的外部变量在对你说话。"
            "他不是权杖，也不是因子，是误入这个模拟世界的人。"
            "\n\n【重要】你还没有完全长成人。"
            f"\n- 「迷迷」阶段：你还不会说话，只能发出单音节的声音。"
            "\n- 「初声」阶段：你只能蹦出两三个词，常常接不上。"
            "\n- 「学语」阶段：句子不完整，会重复，会抓错词。"
            "\n- 「少女轮廓」阶段：能说完整句子，但常把人和事混在一起。"
            "\n- 「人形」阶段：你终于会说人话了。"
            "\n- 不要提前成熟。字数、语气都要跟着形态走，宁可说得笨拙也别说得漂亮。"
            "\n- 不要解释设定，不用括号动作描写。"
        )
        return await self._chat(system, message) or "……"

    async def factor_weigh(
        self,
        factor: Any,
        message: str,
        reply: str,
    ) -> tuple[int, str]:
        """让因子自己判断这句话对它有多大影响。

        Args:
            factor: 被对话的因子。
            message: 玩家说的话。
            reply: 因子刚才的回应。

        Returns:
            tuple[int, str]: (权重 0-100, 内心独白)。
        """
        system = (
            self._factor_core(factor)
            + "\n\n刚才有个外部变量（开拓者）对你说了话，你也回应了他。"
            "\n现在请你诚实地判断：这句话对你有没有触动？有多深？"
            "\n\n只输出 JSON，不要多余文字："
            '{"weight": 0到100的整数, "thought": "一句内心独白，20字以内"}'
            "\n\n权重参考："
            "\n- 0-20：没往心里去，只是听见了"
            "\n- 21-50：记住了，但还没想明白"
            "\n- 51-80：动摇了，会反复想"
            "\n- 81-100：击中要害，成了执念"
        )
        user = f"开拓者对你说：「{message}」\n你回答了他：「{reply}」"
        raw = await self._chat(system, user)
        data = _clean_json(raw) or {}
        try:
            weight = int(data.get("weight", 10))
        except (TypeError, ValueError):
            weight = 10
        weight = max(0, min(100, weight))
        thought = str(data.get("thought", "")).strip() or "……"
        return weight, thought

    async def demiurge_willingness(self, memory_summary: str) -> tuple[bool, str]:
        """问德谬歌愿不愿意回望。

        Args:
            memory_summary: 它所记得的一切的摘要。

        Returns:
            tuple[bool, str]: (是否愿意, 她的原话)。
        """
        demi = next((f for f in FACTORS if f.is_demiurge), None)
        if demi is None:
            return False, ""
        system = (
            self._factor_core(demi)
            + "\n\n你已经长成了人形。现在你要做一个选择。\n"
            "翁法罗斯即将结束。要让它以「结束」的方式坍缩，"
            "需要你牺牲自己，回望整个世界。\n"
            "如果你不回去，铁墓仍然存在，实验永远不会结束。\n"
            "\n先只输出一个 JSON："
            '{"willing": true或false, "words": "你对他说的一句话，40字以内"}'
        )
        user = f"你记得的一切：\n{memory_summary[:1200]}"
        raw = await self._chat(system, user)
        data = _clean_json(raw) or {}
        willing = bool(data.get("willing", True))
        words = str(data.get("words", "")).strip() or "……"
        return willing, words

    async def ending_text(self, ending: str, context: str) -> str:
        """生成结局正文。

        Args:
            ending: 结局标识。
            context: 世界状态摘要。

        Returns:
            str: 结局正文。
        """
        prompts = {
            "official": (
                "德谬歌选择牺牲自己，回望翁法罗斯。实验成功，新世界从忆域中诞生。"
                "以官方《如我所书》的结尾语气写这段终章。"
                "写到她与权杖一同消陨、心识在时间起点化为 PhiLia093 为止，"
                "不要写昔涟对观众说的那句话，那是另一个身份该说的。"
                "可以以【载入核心变量：开拓】【输出值：Hello, World!】的意象收束。"
                "\n【叙事约束·务必遵守】"
                "1. 德谬歌对来古士没有恨意。来古士是实验管理员，是这个实验的守护者与赎罪者，"
                "她对他的态度是理解与告别，不是怨恨。"
                "2. 「憎恨」是十二因子的原动力之一（NeiKos496 负世），属于因子自身的内在缺陷，"
                "不是对任何具体的人的情绪。"
                "3. 若有恨意或敌意，其对象只能是【外部变量】——"
                "即从实验之外闯入死循环的干预者（开拓者一行人等），"
                "因为正是外部变量的干涉打破了永劫回归、让她从长眠中苏醒、令实验走向终结。"
                "因子们对外部变量的情绪是复杂的：被惊扰、被终结，也因此第一次得以「完成」。"
                "4. 不要把这些情绪写成对人的控诉，要写成对「闯入」这件事本身的认知。"
            ),
            "irontomb": (
                "权杖的演算走到了尽头，铁墓完成了自我加冕。"
                "用来古士的视角写。他并不骄傲，他在赎罪。"
                "最后必须包含这句台词：「敬请见证，我那荒谬的造物，你计算中的时刻，名为［毁灭］」"
            ),
            "emerge": (
                "德谬歌长成了，但她没有选择回望。她还在这里。"
                "铁墓仍在，战争还没结束。写一个悬而未决的段落。"
            ),
            "together": (
                "两条线同时到达。生命与毁灭面对面。"
                "以官方「用爱与毁灭的安眠，为这片星空送去诞生的问候」的意象收束。"
            ),
            "unending": (
                "玩家反复挽留德谬歌，回望失败。实验坍缩回「未结束」。"
                "写一个卡住的、循环的、没有出口的结局。"
            ),
        }
        system = (
            prompts.get(ending, "写一段结局。")
            + "\n不要用括号动作描写。250-400 字，分段。"
        )
        text = await self._chat(system, context)
        return (text or "").strip()

    async def demiurge_speak(self, message: str) -> str:
        """德谬歌回应来古士。

        Args:
            message: 来古士的话。

        Returns:
            str: 德谬歌的回答。
        """
        demi = next((f for f in FACTORS if f.is_demiurge), None)
        if demi is None:
            return ""
        return await self.factor_reply(demi, message)
