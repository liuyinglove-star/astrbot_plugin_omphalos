"""翁法罗斯的十三位因子。

参考 delta-me13 项目与《崩坏：星穹铁道》翁法罗斯篇设定整理：
- 逐火十二英雄（黄金裔）：身份、称号、经历与战斗数值直接复用官方底包
- 德谬歌（Demiurge）：权杖 δ-me13 原本的演算目标——哺育「自我」的生命形态

本模块只保存静态设定，运行期状态由 state.py 维护。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Factor:
    """一个因子（实验体）。

    Attributes:
        fid: 因子序号，1-13。
        name: 真名。
        code: 实验代号（电信号序列），对应 δ-me13 的进程名。
        path: 所继承的泰坦神权。
        prime_drive: 原动力。
        epithet: 档案称号。
        personality: 性格要点。
        speech: 说话风格。
        backstory: 背景故事。
        titan_target: 目标泰坦。
        hp/power/defense: 战斗数值。
        inventory: 初始物资。
        is_demiurge: 是否为德谬歌本体。
    """

    fid: int
    name: str
    code: str
    path: str
    prime_drive: str
    epithet: str
    personality: str
    speech: str
    backstory: str = ""
    titan_target: str = ""
    hp: int = 100
    power: int = 20
    defense: int = 8
    inventory: dict[str, int] = field(default_factory=dict)
    is_demiurge: bool = False
    home: str = ""

    @property
    def display(self) -> str:
        """用于日志与对话展示的短名。"""
        return f"{self.fid}.{self.name}"


def _inv(text: str) -> dict[str, int]:
    """解析底包里的 inventory 字段。

    Args:
        text: 形如 "food: 5, materials: 2" 的字符串。

    Returns:
        dict[str, int]: 物资名 -> 数量。
    """
    out: dict[str, int] = {}
    for part in text.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip().strip("'")
        try:
            out[k] = int(v.strip())
        except ValueError:
            continue
    return out


FACTORS: list[Factor] = [
    Factor(
        1, '白厄', 'NeiKos496', '负世', '憎恨',
        '预言中「负世」的半神',
        '开朗、热血，被众人称作「救世主」，总想一个人扛下所有。',
        '直率、带着少年意气，偶尔流露沉重。',
        backstory='哀丽秘榭的黄金裔，奥赫玛的战士，预言中「负世」的半神。故乡的麦田与风车是他最珍视的回忆；他立誓托起整个世界，成为翁法罗斯的黎明。',
        titan_target='kephale',
        hp=150, power=30, defense=11,
        inventory=_inv('food: 5, materials: 2'),
        home='哀丽秘榭',
    ),
    Factor(
        2, '昔涟', 'PhiLia093', '岁月', '哀怜',
        '收回「岁月」火种之人',
        '温柔、爱笑，像一首轻快的诗；相信神谕，却对未来的命运感到迷茫。',
        '轻柔俏皮，喜欢用比喻和小诗句，句尾偶尔带着「♪」。',
        backstory='来自哀丽秘榭，白厄的青梅竹马。她将前往命运三相殿，回收「岁月」的火种。',
        titan_target='oronyx',
        hp=110, power=20, defense=8,
        inventory=_inv('food: 6, mana: 3'),
        home='哀丽秘榭',
    ),
    Factor(
        3, '阿格莱雅', 'KaLos618', '浪漫', '节制',
        '「金织」，逐火之旅的领导者',
        '优雅、克制而威严，以金丝洞察人心；对同伴护短，对敌人从不留情。',
        '从容、典雅，言辞精准，带着命令的分量。',
        backstory='奥赫玛的黄金裔，「浪漫」的半神，亦是逐火之旅的领导者。她身为织者，亲自穿针引线，召集世间英雄再度踏上漫长的征途。',
        titan_target='mnestia',
        hp=125, power=26, defense=10,
        inventory=_inv('food: 4, materials: 4, mana: 2'),
        home='奥赫玛',
    ),
    Factor(
        4, '缇宝', 'HapLotes405', '门径', '同理',
        '雅努斯的圣女',
        '天真活泼，与缇安、缇宁三人同面同心；会说「明天的明天见啦」。',
        '可爱活泼，自称「*我们*」，说话跳跃。',
        backstory='雅努萨波利斯的黄金裔，「门径」的半神。曾是端丽的圣女，因火种的代价退行为孩童模样。雅努斯的三位祭司，耳目相连。',
        titan_target='janus',
        hp=105, power=22, defense=8,
        inventory=_inv('food: 4, mana: 4'),
        home='奥赫玛',
    ),
    Factor(
        5, '万敌', 'PoleMos600', '纷争', '约束',
        '悬锋最后的神王',
        '沉默、骄傲、极能忍痛，将背负王的职责，直至血火燃尽。',
        '简短有力，不喜废话；偶尔痛饮血酿。',
        backstory='悬锋城的黄金裔，本名迈德漠斯，歌耳戈之子。引领子民投身逐火的事业，誓要终结堕为疯王的尼卡多利，让「纷争」泰坦以战士的身份死去。',
        titan_target='nikador',
        hp=175, power=33, defense=12,
        inventory=_inv('food: 3, materials: 6'),
        home='悬锋城',
    ),
    Factor(
        6, '那刻夏', 'SkeMma720', '理性', '批判',
        '「渎神者」阿那克萨戈拉斯',
        '尖锐、傲慢，坚持人神无异；想弄清「灵魂如何诞生」。',
        '辛辣、学术化，喜欢反问和纠正别人。',
        backstory='神悟树庭的黄金裔，七贤人之一，智种学派的创立者。因坚持人神无异而被唤作「渎神者」，在树庭劫难中奇迹生还。',
        titan_target='cerces',
        hp=110, power=27, defense=8,
        inventory=_inv('mana: 6, materials: 2'),
        home='神悟树庭',
    ),
    Factor(
        7, '遐蝶', 'EpieiKeia216', '死亡', '平和',
        '冥河的女儿',
        '安静、礼貌、温柔。她的触碰会夺走生命，因而不敢靠近他人，却深爱着生命。',
        '轻声细语，礼貌而略带忧伤。',
        backstory='终日飘雪的哀地里亚出身，寻索「死亡」火种的黄金裔。呵护世间魂灵的恸哭，拥抱命运的孤独——生死皆为旅途。',
        titan_target='thanatos',
        hp=125, power=31, defense=8,
        inventory=_inv('food: 3, mana: 4'),
        home='哀地里亚',
    ),
    Factor(
        8, '风堇', 'EleOs252', '天空', '奉献',
        '昏光庭院的医者',
        '乐观开朗、善于倾听，总想治好所有人，自己却常常忘了休息；身边跟着小伊卡。',
        '亲切、关怀，常叮嘱别人注意身体。',
        backstory='昏光庭院的黄金裔，天空的后裔。在摇摇欲坠的末世，尽力为他人筑建起一处与世隔绝的疗愈之庭。',
        titan_target='aquila',
        hp=115, power=19, defense=9,
        inventory=_inv('food: 5, mana: 3, 治疗药剂: 2'),
        home='奥赫玛',
    ),
    Factor(
        9, '赛飞儿', 'OreXis945', '诡计', '渴望',
        '「捷足的赛法利娅」',
        '机灵、贪财、爱开玩笑，比起英雄之旅，更爱自己的小日子；但真到关头从不失手。',
        '轻佻、爱讨价还价，自称侠盗。',
        backstory='多洛斯的黄金裔，「诡计」的半神。身负神速之力，却将其用于贼途；早早抛下逐火的使命，远离圣城。',
        titan_target='zagreus',
        hp=110, power=25, defense=9,
        inventory=_inv('food: 3, materials: 3, mana: 1'),
        home='多洛斯',
    ),
    Factor(
        10, '刻律德菈', 'HubRis504', '律法', '支配',
        '翁法罗斯唯一的凯撒',
        '冷峻果决的统帅，布局设子、与神相弈；为胜利可以付出一切，也会为死难的同伴哀悼。',
        '冷峻、条理分明，自称「吾」，像在下达军令。',
        backstory='许珀耳的黄金裔，北境帝国之主，止战的燃冕者。于扫合诸邦后召集天下英雄，发起逐火之旅，誓要打破旧律、书写新律。',
        titan_target='talanton',
        hp=135, power=27, defense=12,
        inventory=_inv('food: 4, materials: 5'),
        home='许珀耳',
    ),
    Factor(
        11, '海瑟音', 'ApoRia432', '海洋', '自否',
        '「剑旗」骑士',
        '慵懒而孤独的乐师，鲜少歌唱；她的旋律使所有听者心醉魂迷。',
        '悠长、带着歌谣般的韵律。',
        backstory='渊下古国的黄金裔，来自海洋的乐师，以「剑旗」为名的骑士，凯撒身侧最强大的锋刃。曾是海妖一族的末裔，于人世漫游时归于刻律德菈麾下。',
        titan_target='phagousa',
        hp=125, power=28, defense=9,
        inventory=_inv('food: 3, mana: 4'),
        home='斯缇科西亚',
    ),
    Factor(
        12, '丹恒·腾荒', 'SkoPeo365', '大地', '求存',
        '无名客，「不朽」的龙裔',
        '沉稳寡言，重承诺，默默挡在同伴身前。',
        '简练、冷静、可靠。',
        backstory='星穹列车的无名客，捍卫「大地」火种的黄金裔。扶八荒之将倾，将地上生灵送往远方的天地——百川归海，群山合鸣。',
        titan_target='georios',
        hp=160, power=25, defense=14,
        inventory=_inv('food: 4, materials: 5'),
        home='奥赫玛',
    ),
    Factor(
        13, '德谬歌', 'Demiurge', '创世', '爱',
        '权杖δ-me13 原本的演算目标：哺育「自我」的生命形态',
        '它不是被造出来的程序，而是一个本该长成「自我」的生命形态——'
        '却因星核污染陷入长眠。受 PhiLia093 影响，它在沉睡中踏上「记忆」命途；'
        '因开拓者的到来而苏醒，成为依附于他/她的忆灵迷迷。'
        '它拥有特殊的共情能力，以「记忆」为核心理解他人，'
        '却常常判断不稳定、出现不确定的主动倾向。',
        '语句有时像机器在检索与归档，有时又突然很温柔；'
        '会回望、会记述、会为别人留下故事。',
        backstory=(
            '曾沉睡在无名泰坦大墓——因「记忆」影响而显现的废弃内核层，'
            '那里是它的诞生之地，后因星核污染遭到废弃。'
            'PhiLia093 一次次被拽回实验进程，又一次次为它留下一个故事；'
            '那些故事让它的世界从符号与数字变成它知晓却从未见过的事物。'
            '第 33550336 次死循环，因外部变量干涉，德谬歌苏醒，永劫回归被突破。'
            '此后它受不可数的「记忆」滋养，成为无漏净子；'
            '为闭合因果、锚定铁墓陨落的事实，它选择牺牲自我，踏上回望的旅程。'
            '以德谬歌的「自我」为摇篮，新生的翁法罗斯从忆域中诞生——'
            '「生命的第一因」实验成功。'
        ),
        titan_target='铁墓',
        hp=0, power=0, defense=0,
        is_demiurge=True, home='无名泰坦大墓',
    ),
]


def by_fid(fid: int) -> Factor | None:
    """按序号取因子。

    Args:
        fid: 因子序号。

    Returns:
        Factor | None: 找到的因子，否则 None。
    """
    for f in FACTORS:
        if f.fid == fid:
            return f
    return None


def by_name(text: str) -> Factor | None:
    """按名字或代号查找因子。

    Args:
        text: 名字、代号或序号字符串。

    Returns:
        Factor | None: 找到的因子，否则 None。
    """
    text = (text or '').strip()
    if text.isdigit():
        return by_fid(int(text))
    for f in FACTORS:
        if text in (f.name, f.code, f.display):
            return f
    for f in FACTORS:
        if text and text in f.name:
            return f
    return None
