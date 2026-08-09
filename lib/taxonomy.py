# -*- coding: utf-8 -*-
"""
分类体系与交叉映射

核心问题：基金季报的行业配置表用的是**证监会 2012 版门类**（A~S，19 类），
而我们要输出的是**申万一级**（31 个）。两套分类不通，必须做映射。

关键事实（也是这套方法最大的软肋）：
    证监会门类里 "C 制造业" 是**一整行**，通常占权益仓位 50%~70%。
    也就是说季报披露的行业约束，对电子/电新/医药/机械/汽车之间怎么分
    几乎没有约束力 —— 而这恰恰是主动权益最主要的战场。

本模块把门类约束转成申万的**分组约束**（"这 15 个申万行业加起来 = 58%"），
组内怎么分完全依赖上期持仓惯性。制造业组的还原误差会被单独统计并报出来，
而不是混在总误差里蒙混过关。
"""

# 申万 2021 版一级行业（31 个）
SW_L1 = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁",
    "801050": "有色金属", "801080": "电子",     "801110": "家用电器",
    "801120": "食品饮料", "801130": "纺织服饰", "801140": "轻工制造",
    "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产",   "801200": "商贸零售", "801210": "社会服务",
    "801230": "综合",     "801710": "建筑材料", "801720": "建筑装饰",
    "801730": "电力设备", "801740": "国防军工", "801750": "计算机",
    "801760": "传媒",     "801770": "通信",     "801780": "银行",
    "801790": "非银金融", "801880": "汽车",     "801890": "机械设备",
    "801950": "煤炭",     "801960": "石油石化", "801970": "环保",
    "801980": "美容护理",
}

SW_NAME_TO_CODE = {v: k for k, v in SW_L1.items()}

# 证监会 2012 门类 -> 可能对应的申万一级行业
# 一对多。用于把门类约束展开成申万分组约束。
CSRC_TO_SW = {
    "A": ["农林牧渔"],
    "B": ["煤炭", "石油石化", "有色金属"],
    "C": [  # 制造业 —— 这一组是软肋，通常占权益仓位一半以上
        # 注意：不含"农林牧渔"。申万的农林牧渔对应 CSRC 的 A 类；
        # C 类下的"农副食品加工业"在申万归入食品饮料，不归农林牧渔。
        # 早期版本把它列进来导致制造业缺口被灌进农林牧渔，误差被放大一个量级。
        "电子", "电力设备", "医药生物", "机械设备", "汽车", "食品饮料",
        "家用电器", "国防军工", "基础化工", "轻工制造", "纺织服饰",
        "钢铁", "有色金属", "建筑材料", "美容护理",
    ],
    "D": ["公用事业"],
    "E": ["建筑装饰", "建筑材料"],
    "F": ["商贸零售"],
    "G": ["交通运输"],
    "H": ["社会服务"],
    "I": ["计算机", "通信", "传媒"],
    "J": ["银行", "非银金融"],
    "K": ["房地产"],
    "L": ["社会服务", "综合"],
    "M": ["社会服务", "计算机"],
    "N": ["环保", "公用事业"],
    "O": ["社会服务"],
    "P": ["社会服务"],
    "Q": ["医药生物"],
    "R": ["传媒", "社会服务"],
    "S": ["综合"],
}

# 门类名称关键词 -> 门类字母（季报里写的是中文全称，需要模糊匹配）
CSRC_NAME_HINTS = [
    ("农", "林", "牧", "渔"), ("采矿",), ("制造",),
    ("电力", "热力", "燃气"), ("建筑业",), ("批发", "零售"),
    ("交通运输", "仓储", "邮政"), ("住宿", "餐饮"),
    ("信息传输", "软件", "信息技术"), ("金融",), ("房地产",),
    ("租赁", "商务服务"), ("科学研究", "技术服务"),
    ("水利", "环境", "公共设施"), ("居民服务", "修理"),
    ("教育",), ("卫生", "社会工作"), ("文化", "体育", "娱乐"),
    ("综合",),
]
_HINT_LETTERS = list("ABCDEFGHIJKLMNOPQRS")

# 制造业组，单独标记用于误差归因
MANUFACTURING_LETTER = "C"


def parse_csrc_letter(name):
    """从季报行业名称中识别证监会门类字母。

    季报里的写法五花八门：'C制造业'、'制造业'、'C 制造业'、
    'I信息传输、软件和信息技术服务业' 等，都要能认出来。
    返回门类字母，认不出返回 None。
    """
    if not name:
        return None
    s = str(name).strip()

    # 形如 'C制造业' / 'C 制造业' —— 开头就是门类字母
    if len(s) >= 2 and s[0].upper() in _HINT_LETTERS and not s[0].isdigit():
        rest = s[1:].strip()
        if rest and not rest[0].isdigit():
            return s[0].upper()

    # 关键词匹配
    for letter, hints in zip(_HINT_LETTERS, CSRC_NAME_HINTS):
        if all(h in s for h in hints) or any(h in s and len(h) >= 3 for h in hints):
            return letter
    return None


def build_group_constraints(alloc_rows):
    """把季报行业配置表转成申万分组约束。

    参数
    ----
    alloc_rows : list of (行业名称, 占净值比例%)

    返回
    ----
    list of dict:
        {letter, name, target, sw_members, is_manufacturing}
      target 为该门类占净值比例（小数）
    """
    groups = []
    for name, pct in alloc_rows:
        letter = parse_csrc_letter(name)
        if letter is None:
            continue
        members = CSRC_TO_SW.get(letter, [])
        if not members:
            continue
        try:
            target = float(pct) / 100.0
        except (TypeError, ValueError):
            continue
        if target <= 0:
            continue
        groups.append({
            "letter": letter,
            "name": str(name).strip(),
            "target": target,
            "sw_members": members,
            "is_manufacturing": letter == MANUFACTURING_LETTER,
        })
    return groups


def constraint_coverage(groups):
    """诊断：约束的"有效性"有多高。

    返回一个字典，说明制造业占了多大比重 —— 这个数越大，
    说明季报约束越弱，结果越依赖持仓惯性假设，可信度越低。
    """
    total = sum(g["target"] for g in groups)
    manu = sum(g["target"] for g in groups if g["is_manufacturing"])
    single = sum(g["target"] for g in groups if len(g["sw_members"]) == 1)
    return {
        "total_equity": total,
        "manufacturing": manu,
        "manufacturing_share": manu / total if total > 0 else 0.0,
        "hard_constrained": single,          # 一对一映射的部分，约束是硬的
        "hard_share": single / total if total > 0 else 0.0,
    }
