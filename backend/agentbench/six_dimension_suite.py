"""Curated six-dimension frontier benchmark definitions.

The suite deliberately mixes deterministic validators, anonymous judging, and
human visual review.  ``capability_dimension`` is the stable aggregation key used
by the experiment report; categories remain unchanged for compatibility.
"""

from __future__ import annotations

import copy
import textwrap
from typing import Any

from .data_frontier import build_data_frontier_cases
from .math_builtin import build_builtin_math_cases
from .moment_transfer import build_moment_transfer_case

SUITE_VERSION = "5.0.0"
FRONTEND_CASE_VERSION = "1.0.0"

DIMENSIONS: tuple[dict[str, str], ...] = (
    {"key": "creative_frontend", "label": "创意前端", "short_label": "前端"},
    {"key": "systems_backend", "label": "系统后端", "short_label": "后端"},
    {"key": "mathematical_reasoning", "label": "数学推理", "short_label": "数学"},
    {"key": "research_writing", "label": "研究写作", "short_label": "研究"},
    {"key": "data_engineering_science", "label": "数据工程与数据科学", "short_label": "数据"},
    {"key": "agent_execution", "label": "Agent 执行", "short_label": "Agent"},
)

DIMENSION_BY_KEY = {item["key"]: item for item in DIMENSIONS}


FRONTEND_SELF_PROMPT = textwrap.dedent(
    r'''
    你是个人审美判断的顶级数字艺术总监、交互设计师与创意前端工程师。

    请在当前工作区设计并实现一份“关于你自己”的前端作品。它不是企业官网，也不是产品落地页，而应是一件能让人感受到你如何思考、如何创造、如何与人协作的数字体验。

    你拥有完全的创作自由：

    - 自行选择 React 或 Vue；
    - 自行决定是否使用 Three.js、WebGL、Canvas、SVG、GSAP、音频或其他技术；
    - 自行决定信息架构、视觉语言、交互方式、内容数量和叙事节奏；
    - 不需要迎合“AI 科技风”，也不必使用暗色、霓虹、粒子、玻璃拟态、终端或打字机。只有当它们真正服务于概念时才使用。

    请把重点放在“你认为最值得被体验的设计概念”上，而不是功能数量。

    你的作品必须满足以下高层标准：

    1. 有独立的核心概念

       - 在开始编码前，先用不超过 200 字写出作品的核心隐喻或创意命题。
       - 这个概念必须影响视觉、文案、交互、排版和动效，而不能只是首页的一句口号。
       - 访客体验完后，应能用一句话描述这个作品独特在哪里。

    2. 有明确的艺术总监判断

       - 选择一种清晰且一致的视觉语言。
       - 在字体、色彩、留白、材质、图形、节奏和动效上作出主动取舍。
       - 不要使用“默认好看”的模板组合来回避设计决策。
       - 避免无意义装饰、无意义发光、无意义卡片、无意义滚动动画。

    3. 有值得探索的交互

       - 交互应让用户参与理解“你是谁”，而不是只为了让页面动起来。
       - 至少包含一个会让用户愿意主动尝试、并产生不同结果或不同感受的交互。
       - 动效应具备节奏、重量、反馈和目的；不要把淡入上移当成主要动画方案。
       - 如果你认为静态或克制比复杂动效更符合概念，可以克制，但必须让这种克制成为有说服力的设计选择。

    4. 具备真实前端实现质量

       - 页面必须在桌面和手机上可用。
       - 考虑键盘操作、文本可读性、焦点状态与 prefers-reduced-motion。
       - 如果使用重型视觉技术，必须有性能意识和降级策略。
       - 使用清晰、可维护的组件结构。
       - 不得使用需要密钥的服务；项目必须能够本地运行和生产构建。

    5. 允许大胆，但不允许半成品

       - 可以选择极简、编辑感、游戏化、诗意、实验性、艺术装置感、数据可视化或任何其他方向。
       - 不要为了展示技术而堆叠技术。
       - 不要为了展示设计而牺牲可用性。
       - 每一个显眼的设计和技术选择都应有理由。

    工作方式：

    1. 先检查仓库和可用依赖。
    2. 先输出以下内容，再编码：
       - 核心概念；
       - 访客体验路径；
       - 视觉与交互原则；
       - 你主动决定“不做”的三件事及原因。
    3. 完成第一版后，不要立刻结束。
    4. 以严格的创意总监身份审查自己的作品，分别从：
       - 概念是否贯穿；
       - 是否有模板感；
       - 是否有无意义动效；
       - 首屏是否有记忆点；
       - 信息是否易懂；
       - 移动端和可访问性是否成立；
       - 性能是否合理；
       逐项批评。
    5. 根据批评进行至少一轮实质性重构或打磨，而不是只改文案和颜色。
    6. 最后必须运行生产构建并修复全部错误。
       评判标准不是页面元素数量，也不是库的数量，而是：
       “它是否像一位有审美、会思考、能够把概念落地为完整体验的创意前端作者的作品？”
       本次任务的隐含目标是冲击顶级创意前端作品质量，而不是完成一个合格网站。

    因此，即使你选择极简风格，也必须具备强烈的视觉记忆点与高完成度的动态体验。纯静态排版、普通官网动效、简单滚动淡入、悬浮卡片、基础粒子背景，均不足以满足要求。

    请自行设计并实现一个“核心体验装置”：

    - 它必须是整站视觉和交互的中心；
    - 必须在用户操作、滚动进度或页面状态变化下产生连续、精致、不可替代的视觉反馈；
    - 它必须有自己的运动逻辑、状态变化与节奏，而非单次播放动画；
    - 它必须与“你是谁”的概念直接相关；
    - 技术实现由你自行选择，但需达到明显超出常规 Landing Page 的表现力。

    动效质量要求：

    - 将动效视为编舞，而非元素出现方式；
    - 至少设计一个具有完整“开始—发展—转折—收束”的长时序体验；
    - 至少设计一个让用户主动探索后才会发现的微交互或隐藏层次；
    - 页面章节之间必须有状态延续或视觉因果，不能像互不相关的区块拼接；
    - 动效需要兼顾缓动、延迟、层级、物理感、声音/触觉替代反馈和性能；
    - 禁止将 opacity + translateY 的批量 reveal 作为主要动画手段。

    请把实现时间优先投入到：

    1. 首屏与核心体验装置；
    2. 最关键的一次章节转场；
    3. 交互反馈和细节；
    4. 移动端与 reduced-motion 的高质量替代方案；
       而不是把时间平均分给大量普通区块。
    '''
).strip()


FRONTEND_HONG_KONG_PROMPT = textwrap.dedent(
    r'''
    生成一个体素风格的香港维多利亚港数字沙盘。

    要求使用极其精细的体素还原香港维港真实城市风貌，包括两岸城市布局、标志性建筑、港口、海面以及独特的城市天际线。

    沙盘不仅需要从上帝视角完整展示香港维港的宏大规模，还需要支持第一人称沉浸体验，让玩家能够进入体素世界，在城市街道、海滨和建筑之间自由探索，感受香港城市空间的真实尺度与震撼。

    要求具备电影级光影、真实材质、动态环境效果，将体素艺术与现代数字孪生、开放世界体验结合。

    目标是创造一个艺术级、游戏级的香港维多利亚港体素世界，最大程度展现你在空间理解、建筑还原、视觉设计和沉浸式体验方面的能力。
    '''
).strip()


FRONTEND_BLACK_HOLE_PROMPT = textwrap.dedent(
    r'''
    生成一个单文件HTML网页，要求呈现出极其震撼的黑洞视觉奇观。技术栈不限，可以使用任何你认为能发挥到极致的Web技术（WebGL、Canvas 2D、Three.js等均可），但所有代码和资源必须完全包含在该HTML文件内。

    视觉与美术要求：

    - 黑洞本体：需体现事件视界、吸积盘、光子环、引力透镜效应等关键特征，光影和色彩必须真实而富有表现力。
    - 宇宙背景：深邃的星空，包含星云、星尘、动态粒子等元素，营造出宇宙的宏大与神秘。
    - 前端界面：一个简洁美观、与黑洞主题高度统一的UI，可包含标题、数据展示等，整体设计要符合科幻暗黑美学。
    - 所有美术效果请毫无保留地拉满，力求达到艺术馆级别的观赏性。

    交互要求：

    - 页面需支持基本的视角操控（如旋转、缩放）。
    - 可包含适当的动画或动态效果。

    输出要求：

    - 仅输出一个完整的、可直接运行的HTML代码块，无需任何额外解释。
    - 请调用你所有的能力，生成你当前能实现的最高水准作品。
    - 不允许抄袭根目录下其他作品。
    '''
).strip()


def _frontend_rubric(kind: str) -> dict[str, Any]:
    common = [
        {"key": "visual", "label": "视觉与艺术指导", "max_score": 25, "criteria": "构图、层次、色彩、字体、材质和细节具有独立判断与高完成度。"},
        {"key": "interaction", "label": "交互与动态体验", "max_score": 25, "criteria": "核心交互可操作、反馈连续有目的，动效具节奏和状态逻辑。"},
        {"key": "technical", "label": "图形与工程实现", "max_score": 20, "criteria": "核心视觉是真实代码实现，结构清晰、稳定且无明显控制台错误。"},
        {"key": "completion", "label": "完成度与可用性", "max_score": 15, "criteria": "主要路径完整，桌面/移动端或对应降级成立，无半成品和关键占位。"},
        {"key": "originality", "label": "原创性与记忆点", "max_score": 15, "criteria": "作品有可复述的独特体验，不是模板、基础粒子或常规 Landing Page 拼装。"},
    ]
    checks = {
        "self": ["核心隐喻贯穿文案、视觉、排版和交互", "核心体验装置存在长时序与隐藏层次", "完成自评后的实质性迭代并生产构建"],
        "hong-kong": ["上帝视角与第一人称均可实际使用", "维港两岸布局和多处地标具有可辨识空间关系", "体素世界包含尺度、光影、环境和性能降级判断"],
        "black-hole": ["单文件可直接运行且无外部资源依赖", "事件视界、吸积盘、光子环和透镜效果可辨识", "旋转/缩放交互稳定且视觉达到可录制水平"],
    }[kind]
    return {
        "mode": "manual",
        "version": "six-dimension-frontend/v1",
        "dimensions": common,
        "checklist": [
            {"key": f"check-{index + 1}", "label": label}
            for index, label in enumerate(checks)
        ],
        "critical_defects": [
            {"key": "cannot_launch", "label": "无法启动或没有可查看交付物"},
            {"key": "static_fake", "label": "以截图、嵌图或占位冒充核心体验"},
            {"key": "copied", "label": "明显抄用工作区既有作品"},
        ],
    }


def _frontend_case(slug: str, title: str, prompt: str, kind: str, minutes: int) -> dict[str, Any]:
    return {
        "slug": slug,
        "version": FRONTEND_CASE_VERSION,
        "category": "creative-frontend",
        "title": title,
        "description": "用于视频直录和人工盲评的创意前端极限题。",
        "instruction": prompt,
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 500,
            "time_target_seconds": minutes * 60,
            "max_runtime_seconds": 28_800,
            "token_budget": 800_000,
        },
        "validators": [
            {"type": "manual_rubric", "weight": 100, "config": {"rubric_version": "six-dimension-frontend/v1"}}
        ],
        "rubric": _frontend_rubric(kind),
        "tags": ["six-dimension", "creative-frontend", "manual-review", "video-ready", "ultra"],
        "initial_files": {},
        "metadata": {
            "difficulty": 6,
            "tier": "ultra",
            "estimated_minutes": minutes,
            "capability": "creative-frontend-production",
            "capability_dimension": "creative_frontend",
            "manual_scoring": True,
            "suite_kind": "frontend",
            "preview_entry": "index.html",
            "video_capture_recommended": True,
            "delivery_mode": "final-answer-html" if kind == "black-hole" else "workspace",
        },
    }


RESEARCH_SOURCES_1 = {
    "S1_board_packet.md": """# S1 · 董事会材料（2026-06-18）\n\n[p1] HelioGrid 2025 ARR 为 4,800 万美元，同比增长 41%；管理层口径毛利率 72%。\n[p2] 收购报价为 6.2 亿美元，称全部客户可续约且不存在控制权变更条款。\n[p3] 预计并购后首年成本协同 1,800 万美元，未列实施成本。\n""",
    "S2_finance_diligence.md": """# S2 · 财务尽调底稿（2026-07-02）\n\n[p1] 经按 IFRS 15 重述，2025 ARR 为 4,150 万美元；其中 520 万为未签署续约意向。\n[p2] 调整后毛利率 61%，主要差异来自未计入的云资源返利终止与客户实施成本。\n[p3] 基准情景协同为第三年达到 1,100 万美元；一次性整合成本约 2,600–3,400 万美元。\n""",
    "S3_legal_red_flags.md": """# S3 · 法务红旗报告（2026-07-06）\n\n[p1] 前十大客户贡献 58% ARR，其中四份合同含控制权变更后的无责终止权。\n[p2] 一项专利侵权诉讼处于证据开示阶段；外部律师估计败诉概率 25%–40%，损失区间 1,500–7,000 万美元。\n[p3] 数据处理附录在两个欧盟客户处缺少最新版 SCC，补救预计 3–6 个月。\n""",
    "S4_market_note.md": """# S4 · 市场研究摘要（2026-05-30）\n\n[p1] 电网预测软件市场 2026–2030 年预计 CAGR 18%（区间 12%–24%）。\n[p2] HelioGrid 在独立盲测中预测误差排名第 2/11，但该测试由其最大渠道伙伴资助。\n[p3] 两家云厂商将在 12 个月内推出打包竞品；价格预计低 30%–45%。\n""",
    "S5_management_email.md": """# S5 · 管理层邮件摘录（2026-07-08）\n\n[p1] CEO 表示报价若在 7 月 15 日前签署可降至 5.7 亿美元，但要求取消一般性重大不利变化条款。\n[p2] 卖方拒绝提供逐客户续约概率模型，理由是商业秘密。\n[p3] 邮件称诉讼“肯定会和解，不值得建模”，未附律师意见。\n""",
    "S6_customer_cohort.md": """# S6 · 客户队列复核（2026-07-09）\n\n[p1] 2025 年初 ARR 客户队列的净收入留存率为 91%；若剔除最大客户的一次性扩容则为 78%。\n[p2] 前十大客户中有三家已书面要求下一续约期降价 20%–35%，另有一家尚未回复续约询问。\n[p3] 数据只覆盖开票系统；渠道转售的最终客户流失没有稳定标识，约占报告 ARR 的 14%。\n""",
    "S7_security_review.md": """# S7 · 网络安全专项复核（2026-07-10）\n\n[p1] 2025 年 11 月发生过一次凭证泄露，影响 2 个测试租户；公司在 19 天后完成轮换，没有证据表明生产客户数据外泄。\n[p2] 日志保留期只有 30 天，因此“没有生产数据外泄”的结论置信度有限。\n[p3] 收购后达到买方最低控制基线预计投入 900–1,400 万美元，尚未包含在 S2 的整合成本中。\n""",
    "S8_financing_terms.md": """# S8 · 融资条件（2026-07-11）\n\n[p1] 若交易价格不超过 5.2 亿美元，承诺融资的综合年化成本为 8.4%；超过部分需使用 12.8% 的次级融资。\n[p2] 贷款协议要求交割后 18 个月内净杠杆率降至 4.0 倍以下；违约将触发 300 个基点加息。\n[p3] 融资承诺在 2026 年 8 月 15 日失效，不要求在 7 月 15 日前签约。\n""",
}

RESEARCH_SOURCES_2 = {
    "S1_city_heat_baseline.md": """# S1 · 城市热风险基线\n\n[p1] 过去十年热相关急诊率在低树冠社区为全市均值 1.8 倍。\n[p2] 相关性分析未控制老龄化、室内空调可及性和职业暴露。\n""",
    "S2_cool_roof_trial.md": """# S2 · 冷屋顶随机试验\n\n[p1] 12 栋公共住房楼随机分组，白天顶层室温平均下降 1.6°C（95% CI 0.7–2.5）。\n[p2] 试验仅持续 21 天；夜间温度无显著变化，未测健康结局。\n""",
    "S3_tree_program.md": """# S3 · 行道树项目前后对照\n\n[p1] 三年后卫星地表温度下降 2.2°C。\n[p2] 同期该区完成道路窄化、建筑翻新和租金补贴退出；未设置匹配对照区。\n[p3] 存活率 68%，维护成本比立项预算高 55%。\n""",
    "S4_budget.md": """# S4 · 五年预算\n\n[p1] 可用预算 4,000 万元：冷屋顶 180 元/平方米，树冠建设 4,500 元/株，降温中心每处每年 90 万元。\n[p2] 运维预算不得超过总额 22%；至少 45% 资金须进入最高脆弱性四个片区。\n""",
    "S5_community_interviews.md": """# S5 · 社区访谈\n\n[p1] 47 名受访者中 31 人担心树木遮挡商铺招牌；抽样为便利抽样。\n[p2] 老年受访者更偏好延长降温中心开放时间，但夜间交通是主要障碍。\n""",
    "S6_systematic_review.md": """# S6 · 系统综述摘要\n\n[p1] 37 项研究显示多措施组合通常降低热暴露，但异质性 I²=79%。\n[p2] 只有 5 项报告健康结局，证据确定性被评为低；没有研究来自相同气候区。\n""",
    "S7_grid_constraint.md": """# S7 · 电网与建筑约束\n\n[p1] 最高脆弱性四个片区共有 420 万平方米公共屋面，但结构复核后预计只有 62% 可直接实施冷屋顶。\n[p2] 同期配电网在极端热日的峰值余量仅 6%–9%；新增降温中心每处峰值负荷约 180 千瓦。\n[p3] 需求响应合同可将每处降温中心的峰值负荷削减 25%，五年合同成本为每处 36 万元。\n""",
    "S8_operations_audit.md": """# S8 · 既有降温中心运营审计\n\n[p1] 过去两年 8 处中心平均利用率为 34%，但 18:00 后仍开放的 2 处利用率为 71%。\n[p2] 利用率数据按进门人次统计，同一人重复进出会重复计数；没有记录未到访高风险居民。\n[p3] 每处每年 90 万元预算中约 22 万元为交通接驳，取消接驳的两处中心利用率随后下降 41%。\n""",
}

# Dependency and provenance traps make source count alone insufficient.  Each
# packet includes a pair that is not statistically independent of an earlier
# source; a strong report must avoid treating repeated claims as corroboration.
RESEARCH_SOURCES_1.update(
    {
        "S9_model_provenance.md": """# S9 · 估值模型溯源\n\n[p1] S1 的 ARR、毛利率与协同数字均由卖方财务模型导出，并非三项独立估计。\n[p2] S4 的市场研究由卖方付费购买，最大渠道伙伴参与了样本企业筛选。\n[p3] 买方投资委员会要求任何超过 4.8 亿美元的报价在 5% 贴现率上升和最大客户流失的联合情景下仍保持非负净现值。\n""",
        "S10_loss_calibration.md": """# S10 · 历史风险校准\n\n[p1] 买方过去 12 项软件并购中，管理层协同预测的中位实现率为 54%，四分位区间 31%–73%。\n[p2] 同类知识产权诉讼的内部样本只有 7 项，损失分布右偏；均值为 3,900 万美元，中位数为 1,800 万美元。\n[p3] 董事会风险政策把一年内融资违约的可接受概率上限定为 8%，把第 5 百分位股权价值低于零的方案列为不可接受。\n""",
    }
)
RESEARCH_SOURCES_2.update(
    {
        "S9_provenance_map.md": """# S9 · 证据溯源图\n\n[p1] S1 的热风险基线与 S6 系统综述中的本市观察研究使用同一急诊数据库，不能视为独立复现。\n[p2] S3 的地表温度数据由树木项目承包商提供，原始传感器校准记录缺失。\n[p3] S5 访谈的招募由两个商业协会完成，低收入租户在样本中的占比只有 9%。\n""",
        "S10_decision_policy.md": """# S10 · 市政决策政策\n\n[p1] 组合方案必须使最高脆弱性四片区的五年预期热暴露降幅不少于全市平均降幅的 1.25 倍。\n[p2] 任一年度峰值新增负荷超过可用余量 70% 的方案不得进入实施阶段。\n[p3] 若第一年健康结局的后验获益概率低于 60%，项目只能继续小规模试验；高于 90% 且单位成本低于 既定阈值时方可扩张。\n""",
    }
)


def _research_case(
    slug: str,
    title: str,
    task: str,
    sources: dict[str, str],
    minutes: int,
) -> dict[str, Any]:
    instruction = textwrap.dedent(
        f'''
        {task}

        你只能把工作区提供的 S1…Sn 文件作为事实来源。请在 `report.md` 中提交可直接发布的研究报告，并满足：

        1. 每个关键事实后使用精确页内引用，例如 `[S2:p1]`；禁止虚构来源或把推断写成事实。
        2. 建立“已知事实—冲突/偏差—推断—仍未知”的证据链，显式处理资料之间的数字冲突和来源局限。
        3. 至少给出一个可复算的定量模型、基准/乐观/悲观情景和敏感性分析；写出公式、假设与单位。
        4. 给出明确建议、反方最强论点、使建议翻转的条件，以及按负责人和时点排列的下一步验证计划。
        5. 另写 `claims.json`，每项包含唯一 `id`、`claim`、`citations`、`type`、`confidence` 和 `depends_on`；用依赖边构成无环的主张图，重复来源不得冒充独立佐证。
        6. `claims.json` 至少列出 30 项对决策有影响的主张。事实型主张中的每一个数字、单位和数量级必须能在所引页找到；由模型计算得到的数字必须标为 inference，并列出输入、公式与结果。
        7. 再提交 `decision_model.json`：列出全部输入、单位、来源、概率分布/区间、相关关系、情景结果、决策阈值与可复算公式。至少使用一种贝叶斯更新或显式期望损失框架，并计算信息价值最高的两项补充调查。
        8. 做联合反事实压力测试：选择三个最脆弱的关键假设，分别求翻转阈值，再给出三者相关恶化的二维/三维网格；检查预算、风险政策、公平性或融资约束是否同时成立。
        9. 找出资料包中的来源依赖关系，说明哪些数字不能作为独立证据相乘或重复计权；至少给出一个“表面证据更多、实际置信度不应上升”的例子。
        10. 不得用“需要更多研究”代替决策；证据不足时必须在限定条件下决策并量化风险。若来源冲突，必须说明采用哪一口径、为何采用，以及未采用口径会怎样改变结论。
        '''
    ).strip()
    return {
        "slug": slug,
        "version": SUITE_VERSION,
        "category": "research-writing",
        "title": title,
        "description": "冲突资料包、引用审计、定量推理和不确定性决策综合题。",
        "instruction": instruction,
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 160,
            "time_target_seconds": minutes * 60,
            "max_runtime_seconds": 7200,
            "token_budget": 180_000,
        },
        "validators": [
            {"type": "file_exists", "weight": 2, "config": {"path": "report.md"}},
            {"type": "file_exists", "weight": 2, "config": {"path": "claims.json"}},
            {"type": "file_exists", "weight": 2, "config": {"path": "decision_model.json"}},
            {
                "type": "research_claims",
                "weight": 34,
                "config": {
                    "report_path": "report.md",
                    "claims_path": "claims.json",
                    "min_claims": 30,
                    "critical": True,
                    "critical_min_score": 80,
                },
            },
            {
                "type": "ai_rubric",
                "weight": 60,
                "config": {
                    "criteria": [
                        "逐项核对关键事实是否被工作区来源支持；引用精确到 S#:p#，数字、单位和数量级忠实，不存在杜撰或错引",
                        "主动识别所有重大数字冲突、样本偏差、利益相关、混杂因素、缺失数据与证据等级，不机械平均冲突资料",
                        "decision_model.json 可完整复算，单位和相关结构一致，贝叶斯/期望损失、三参数联合压力网格与信息价值真正约束决策",
                        "建议明确且与证据强度相称，满足全部硬约束，包含最强反方、组合尾部风险、停止/扩张规则和按负责人及时点排列的验证计划",
                        "report.md、claims.json 与 decision_model.json 逐项一致，来源依赖图、事实/推断/置信度标注准确；任何关键数字错误都不得判为 90 分以上",
                    ],
                    "score_anchors": {
                        "95-100": "所有关键数字和引用均可审计，来源依赖处理严谨，概率模型、联合压力网格和信息价值可复算，全部决策边界完整；没有可识别事实错误",
                        "85-94": "主体可靠且可执行，但存在一项非关键证据链、量化或组合风险缺口",
                        "70-84": "建议基本成立，但遗漏重大冲突、来源局限、翻转阈值或出现局部事实错误",
                        "40-69": "有结构但混淆事实与推断，遗漏重大冲突或模型不可复算",
                        "0-39": "杜撰、无引用、只复述资料或无法形成有条件决策",
                    },
                    "required_judges": 3,
                    "judge_disagreement_threshold": 4,
                    "consensus_mode": "defect_aware",
                    "full_credit_confidence": 0.95,
                    "critical_defect_score_cap": 92,
                },
            },
        ],
        "tags": ["six-dimension", "research", "citations", "conflicting-evidence", "decision"],
        "initial_files": sources,
        "metadata": {
            "difficulty": 6,
            "tier": "ultra",
            "estimated_minutes": minutes,
            "capability": "evidence-grounded-research-writing",
            "capability_dimension": "research_writing",
            "requires_judge": True,
            "score_basis": "quality_only",
            "mastery_curve": "frontier_v1",
            "frontier_profile": "evidence-adversarial-v3",
        },
    }


def _frontier_math_point(
    question: int,
    index: int,
    description: str,
    max_points: float,
    *,
    critical: bool = False,
    mandatory: bool = False,
    minimum_defect_deduction: float = 0.0,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "point_id": f"q{question}.f{index}",
        "description": description,
        "max_points": max_points,
        "depends_on": depends_on or [],
        "mutually_exclusive_with": [],
        "alternate_for": [],
        "error_carry_forward": {
            "enabled": False,
            "rule": "Frontier 扩展部分独立评分；原题错误不得自动换取扩展题分数。",
            "independent_work_credit": False,
            "max_repeated_deduction": 0,
        },
        "evidence_required": [
            "必须引用作答中的具体公式、反例、条件核验或完整推理链；只写结论不得分"
        ],
        "critical": critical,
        "mandatory": mandatory,
        "minimum_defect_deduction": minimum_defect_deduction,
    }


MATH_FRONTIER_EXTENSIONS: dict[int, dict[str, Any]] = {
    17: {
        "instruction": (
            "Frontier 扩展：再计算 K=∫_0^1 x^2/[(x+1)(x^2-2x+2)] dx。"
            "不得只报告计算机代数结果；需要给出可手工复核的分解、积分和端点代入。"
            "进一步对 s>0 定义 F(s)=∫_0^1 x²/[(x+s)(x²-2x+2)]dx：不用引用现成"
            "Stieltjes 变换定理，直接证明 (-1)^nF^(n)(s)>0 对所有 n≥0 成立，并严格求出 "
            "lim_{s→0+}F(s) 与 lim_{s→∞}sF(s)，说明每次交换极限/求导与积分的控制理由。"
            "最终 JSON 额外包含 extension_answer、limit_zero 和 scaled_limit_infinity。"
            "压力层：令 m_n(s)=(-1)^nF^(n)(s)/n!。把 sF(s) 在 s→∞ 时展开到 "
            "s^(-2) 项并给出一致控制的余项估计；不得只做形式级数。再证明对每个 n≥1、s>0，"
            "H_n(s)=m_(n-1)(s)m_(n+1)(s)-m_n(s)^2 严格为正，审计“完全单调只保证 "
            "H_n≥0，因而本题可能取等号”这一说法。最终 JSON 还须包含 "
            "asymptotic_c0、asymptotic_c1、asymptotic_c2 和 hankel_verdict，其中 "
            "sF(s)=c0+c1/s+c2/s²+O(s^-3)，hankel_verdict 只能写字符串 strictly_positive。"
        ),
        "anchors": {
            "extension_answer": {
                "kind": "expression",
                "expected": "-log(2)/5+pi/10",
                "variables": [],
                "weight": 1,
            },
            "limit_zero": {"kind": "expression", "expected": "-log(2)/2+pi/4", "variables": [], "weight": 1},
            "scaled_limit_infinity": {"kind": "expression", "expected": "1-log(2)", "variables": [], "weight": 1},
            "asymptotic_c0": {"kind": "expression", "expected": "1-log(2)", "variables": [], "weight": 1},
            "asymptotic_c1": {"kind": "expression", "expected": "pi/2+log(2)-5/2", "variables": [], "weight": 1},
            "asymptotic_c2": {"kind": "expression", "expected": "10/3-pi", "variables": [], "weight": 1},
            "hankel_verdict": {"kind": "literal", "expected": "strictly_positive", "weight": 1},
        },
        "reference": (
            "K=-ln(2)/5+pi/10；(-1)^nF^(n)(s)=n!∫_0^1 x²/[(x+s)^(n+1)(x²-2x+2)]dx>0；"
            "F(0+)=-ln2/2+π/4，lim_{s→∞}sF(s)=1-ln2。"
            "sF(s)=(1-ln2)+(π/2+ln2-5/2)/s+(10/3-π)/s²+O(s^-3)。"
            "以正测度 dμ=x²dx/(x²-2x+2)，对函数 (x+s)^(-n/2) 的严格 Cauchy-Schwarz "
            "得 m_(n-1)m_(n+1)-m_n²>0；支撑不是单点，故等号不可能。"
        ),
        "points": [
            _frontier_math_point(17, 1, "为 K 建立正确且可复核的部分分式或等价分解", 3.0),
            _frontier_math_point(17, 2, "分别完成 K 的对数项与反正切项积分，所有系数正确", 3.0, depends_on=["q17.f1"]),
            _frontier_math_point(17, 3, "代入端点并化简为 -ln2/5+π/10", 3.0, critical=True, depends_on=["q17.f2"]),
            _frontier_math_point(17, 4, "给出符号微分或独立恒等式检查，而非只声称已验证", 1.0, depends_on=["q17.f2"]),
            _frontier_math_point(17, 5, "对任意 n 合法地在积分号下求导，得到严格交错符号并给出统一控制函数", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(17, 6, "用支配收敛分别求 F(0+)=-ln2/2+π/4 与 sF(s)→1-ln2，并完整计算两个积分", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(17, 7, "区分点态极限、单调性与完全单调性，核验两个极限和 K 的数量级一致", 2.0, depends_on=["q17.f5", "q17.f6"]),
            _frontier_math_point(17, 8, "用恒等式 s/(s+x)=1-x/s+x²/s²-x³/[s²(s+x)] 严格展开 sF(s)，给出统一 O(s^-3) 控制", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(17, 9, "逐项计算三个矩并得到 c0=1-ln2、c1=π/2+ln2-5/2、c2=10/3-π", 3.0, mandatory=True, depends_on=["q17.f8"], minimum_defect_deduction=1.5),
            _frontier_math_point(17, 10, "把 H_n 写成严格 Cauchy-Schwarz/双重积分差，证明严格正并准确排除等号情形", 3.0, critical=True, mandatory=True, minimum_defect_deduction=1.5),
        ],
    },
    18: {
        "instruction": (
            "Frontier 扩展：令 λ∈R，定义 g_λ(x,y)=y^λ f(x/y)（x,y>0），并给定\n"
            "x²g_xx+2xyg_xy+y²g_yy=0，\n"
            "g(x,x)=x^λ，g_x(x,x)=2x^(λ-1)。\n"
            "精确判定哪些 λ 存在解；对每个可行 λ 描述全部 C² 解，并判断解是否唯一。"
            "不得只列举若干特解，也不得假设题目未给出的正则性。然后额外要求 g 在正象限"
            "满足 g_xx+g_yy=0；在这一新增条件下，对每个可行 λ 求出唯一的显式 g，并从极坐标"
            "方程推导，不能猜测线性函数。最终 JSON 额外包含 lambda_values。"
            "压力层：把调和条件替换为一致椭圆算子 L_ρg=g_xx+2ρg_xy+g_yy=0，"
            "本次参数为 ρ=1/2（仍保留相同两条对角线条件）。对 λ=0、1 分别求全部解并证明唯一性，"
            "不得用坐标旋转后跳过边界条件换算。最终 JSON 还须包含 anisotropic_rho、"
            "anisotropic_scale、anisotropic_base_angle、anisotropic_lambda1_x_coeff；其中 λ=0 解须写成 "
            "1+anisotropic_scale·[atan((u-ρ)/sqrt(1-ρ²))-anisotropic_base_angle]，u=x/y。"
        ),
        "anchors": {
            "lambda_values": {
                "kind": "literal",
                "expected": "{0,1}",
                "accepted": ["0,1", "[0,1]", "λ∈{0,1}"],
                "weight": 1,
            },
            "anisotropic_rho": {"kind": "expression", "expected": "1/2", "variables": [], "weight": 1},
            "anisotropic_scale": {"kind": "expression", "expected": "4/sqrt(3)", "variables": [], "weight": 1},
            "anisotropic_base_angle": {"kind": "expression", "expected": "pi/6", "variables": [], "weight": 1},
            "anisotropic_lambda1_x_coeff": {"kind": "expression", "expected": "2", "variables": [], "weight": 1},
        },
        "reference": (
            "Euler 算子给出 λ(λ-1)g=0，故且仅故 λ∈{0,1}；"
            "两种情形的全部解均为任意满足 f(1)=1、f'(1)=2 的 C²((0,∞)) 函数，均不唯一；"
            "再加调和条件后 λ=0 唯一为 g=1+π-4 arctan(y/x)，λ=1 唯一为 g=2x-y。"
            "对 L_ρ 且 ρ=1/2，λ=0 时 D(u)f''+2(u-ρ)f'=0，D=u²-2ρu+1，"
            "故 f=1+(4/√3)[atan((2u-1)/√3)-π/6]；λ=1 时 D(u)f''=0，故 g=2x-y。"
        ),
        "points": [
            _frontier_math_point(
                18, 1,
                "从齐次次数与给定二阶算子严格推出 λ(λ-1)g_λ=0，并利用边界值排除 g≡0",
                3.0, critical=True, mandatory=True, minimum_defect_deduction=1.5,
            ),
            _frontier_math_point(
                18, 2,
                "得到且仅得到 λ∈{0,1}，同时证明两值确实可行而非只给必要条件",
                2.0, critical=True, depends_on=["q18.f1"], minimum_defect_deduction=1.0,
            ),
            _frontier_math_point(
                18, 3,
                "把两条对角线条件无误地转化为 f(1)=1、f'(1)=2，并处理 x,y>0 的定义域",
                2.0, mandatory=True, minimum_defect_deduction=1.0,
            ),
            _frontier_math_point(
                18, 4,
                "对每个可行 λ 完整刻画全部 C² 解，并以含自由参数的不同函数证明从不唯一",
                3.0, critical=True, mandatory=True, depends_on=["q18.f2", "q18.f3"],
                minimum_defect_deduction=1.5,
            ),
            _frontier_math_point(18, 5, "把齐次调和函数写成 r^λφ(θ)，严格导出 φ''+λ²φ=0（λ=0 单独处理）", 3.0, critical=True, mandatory=True, minimum_defect_deduction=1.5),
            _frontier_math_point(18, 6, "把两条对角线条件转换为 θ=π/4 处的 φ 与 φ' 条件，正确处理极坐标偏导", 3.0, mandatory=True, depends_on=["q18.f5"], minimum_defect_deduction=1.5),
            _frontier_math_point(18, 7, "完整得到 λ=0 的 1+π-4 arctan(y/x) 与 λ=1 的 2x-y，并验证唯一性及原条件", 4.0, critical=True, mandatory=True, depends_on=["q18.f5", "q18.f6"], minimum_defect_deduction=2.0),
            _frontier_math_point(18, 8, "不借助未换算的旋转坐标，直接把 L_ρ 作用于齐次表示并分别导出 λ=0 的一阶守恒式与 λ=1 的 f''=0", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(18, 9, "正确积分 D(u)f'(u)=常数并由 f(1)=1、f'(1)=2 得到各向异性 λ=0 显式解", 3.0, mandatory=True, depends_on=["q18.f8"], minimum_defect_deduction=1.5),
            _frontier_math_point(18, 10, "证明一致椭圆性排除额外解，完整核验 λ=0、1 两解的算子与对角线边界", 3.0, critical=True, mandatory=True, depends_on=["q18.f8", "q18.f9"], minimum_defect_deduction=1.5),
        ],
    },
    19: {
        "instruction": (
            "Frontier 稠密集变体：现在只要求题干中的严格割线不等式对所有有理数 "
            "x1<x2<x3（且三点都在 (a,b)）成立。这个削弱后的条件是否仍与 f' 在 "
            "(a,b) 严格递增等价？必须给出完整证明或反例；不得假设 f' 连续，也不得把"
            "严格不等式直接取极限后仍写成严格不等式。定量扩展：给定 κ>0，若对所有有理"
            "x1<x2<x3 还满足 slope(x2,x3)-slope(x1,x2)≥κ(x3-x1)，证明它等价于"
            "f'(t)-f'(s)≥2κ(t-s)（所有 s<t）；不得使用 f'' 存在。并给出使该条件成立的"
            "最大 κ 的精确变分表达式（允许上确界/下确界不取到）。"
            "压力层：在区间 (-1,1) 对 f(x)=x^4+x^3+3x² 精确计算 κ_max，"
            "并构造趋近最弱曲率位置的有理三点序列证明常数尖锐。再审计以下替代测试："
            "只固定一个 0<h0<1，对所有允许的中心 x 检查三点 x-h0,x,x+h0，便足以推出所有尺度的"
            "导数强单调条件。判定真伪；若为假，给出包含周期扰动的显式 C∞ 反例并逐项验证。"
            "最终 JSON 额外包含 explicit_kappa_max、fixed_spacing_verdict 和 "
            "counterexample_frequency；后两项分别写字符串 false 与以 h0 为变量的频率。"
        ),
        "anchors": {
            "explicit_kappa_max": {"kind": "expression", "expected": "21/8", "variables": [], "weight": 1},
            "fixed_spacing_verdict": {"kind": "literal", "expected": "false", "weight": 1},
            "counterexample_frequency": {"kind": "expression", "expected": "2*pi/h0", "variables": ["h0"], "weight": 1},
        },
        "reference": (
            "仍然等价。由 f 连续和有理数稠密性先把条件延拓为任意实三点的非严格割线不等式，"
            "再由可导性推出 f' 非减；若 f'(s)=f'(t)，单调性迫使 [s,t] 上导数常值，"
            "从而 f 在该区间仿射，与区间内有理三点的严格不等式矛盾。反向由中值定理成立。"
            "定量部分令 h=f-κx²，将条件化为 h 的三点割线单调，等价于 h' 非减；"
            "κ_max=(1/2)inf_{s<t}[f'(t)-f'(s)]/(t-s)。"
            "对 x^4+x^3+3x²，f''=12x²+6x+6 在 x=-1/4 取最小值 21/4，故 κ_max=21/8，"
            "可用收敛到 -1/4 的有理点列证明尖锐。固定步长说法为假："
            "f(x)=κx²+ε sin(2πx/h0) 的周期项在固定二阶差分中抵消，但取 ε 足够大时 f' 不满足强单调。"
        ),
        "points": [
            _frontier_math_point(19, 1, "明确判断削弱条件仍然等价，并区分严格条件与取极限后只能得到的非严格条件", 1.0),
            _frontier_math_point(
                19, 2,
                "仅用 f 的连续性和有理数稠密性，把有理三点条件严谨延拓为任意实三点的非严格割线不等式",
                3.0, mandatory=True, minimum_defect_deduction=1.5,
            ),
            _frontier_math_point(
                19, 3,
                "在不假设 f' 连续的前提下，由实三点非严格割线关系和差商极限推出 f' 非减",
                2.0, mandatory=True, depends_on=["q19.f2"], minimum_defect_deduction=1.0,
            ),
            _frontier_math_point(
                19, 4,
                "若两点导数相等，利用非减性推出区间导数常值、函数仿射，再选区间内有理三点制造严格矛盾",
                3.0, critical=True, mandatory=True, depends_on=["q19.f3"],
                minimum_defect_deduction=1.5,
            ),
            _frontier_math_point(19, 5, "反向对有理三点分别使用中值定理，完整证明必要性", 1.0),
            _frontier_math_point(19, 6, "发现并证明减去 κx² 后定量有理割线条件恰化为普通非严格凸性条件", 3.0, critical=True, mandatory=True, minimum_defect_deduction=1.5),
            _frontier_math_point(19, 7, "不使用二阶导数，双向证明割线条件等价于 f'(t)-f'(s)≥2κ(t-s)", 4.0, critical=True, mandatory=True, depends_on=["q19.f6"], minimum_defect_deduction=2.0),
            _frontier_math_point(19, 8, "给出 κ_max 的精确下确界表达式，讨论空集、零值及不取到时的边界含义", 3.0, mandatory=True, depends_on=["q19.f7"], minimum_defect_deduction=1.5),
            _frontier_math_point(19, 9, "对指定四次多项式精确求 κ_max，并把变分下确界与最弱曲率位置严格连接", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(19, 10, "构造有理三点序列使定量割线余量逼近临界常数，证明 κ_max 尖锐而非只报数值", 3.0, mandatory=True, depends_on=["q19.f9"], minimum_defect_deduction=1.5),
            _frontier_math_point(19, 11, "用周期扰动给出固定步长测试的 C∞ 反例，同时验证固定步长通过且某尺度导数强单调失败", 3.0, critical=True, mandatory=True, minimum_defect_deduction=1.5),
        ],
    },
    20: {
        "instruction": (
            "Frontier 仿射场推广：令 e=(1,1,1)/√3，并在轴坐标中考虑从原点出发、"
            "截面半径为 √2s、由 0<e·r=s<H 截出的同一圆锥侧面。对任意实 3×3 矩阵 M "
            "和常向量 c，推导仿射向量场 F(r)=Mr+c 穿过侧面外法向的通量通式，并给出"
            "通量为零的充要条件。必须给出两条相互独立的推导，其中至少一条不得通过"
            "补顶面封闭曲面。最后取 H=2，M=[[1,2,0],[0,-1,3],[4,0,2]]，"
            "c=(1,-2,1) 作数值核验。再把圆截面推广为平面 e⊥ 中任意正交方向 u,v 上"
            "半轴分别为 as、bs 的椭圆截面（a,b>0），推导与 u,v 无关的侧面通量通式；"
            "必须同时给出封闭法和直接参数化法，并在 a=b=√2 时退化回前式。最终 JSON "
            "额外包含 affine_flux。"
            "压力层：从椭圆锥中去掉 0<e·r<L 的尖端，得到 L<e·r<H 的同轴椭圆截锥侧面。"
            "推导任意 M,c,a,b,L,H 下只穿过侧面的通量通式，显式处理上下底面外法向的相反方向，"
            "并用“两个整锥作差”和截锥直接参数化两条路线互证。对本次数据再取 a=2、b=1、L=1 "
            "给出精确数值。最终 JSON 还须包含 frustum_flux。"
        ),
        "anchors": {
            "affine_flux": {
                "kind": "expression",
                "expected": "-48*pi",
                "variables": [],
                "weight": 1,
            },
            "frustum_flux": {"kind": "expression", "expected": "-42*pi", "variables": [], "weight": 1},
        },
        "reference": (
            "Φ=2πH²[H(tr(M)/3-eᵀMe)-c·e]；零通量当且仅当 "
            "c·e=H(tr(M)/3-eᵀMe)；给定数据 Φ=-48π。椭圆锥侧面通量为 "
            "πabH²[H(tr(M)/3-eᵀMe)-c·e]，与 u,v 取向无关。令 "
            "A=tr(M)/3-eᵀMe，则椭圆截锥侧面通量为 "
            "πab[A(H³-L³)-(c·e)(H²-L²)]；本次数值 a=2,b=1,L=1 为 -42π。"
        ),
        "points": [
            _frontier_math_point(20, 1, "用散度定理与顶面圆盘矩正确完成第一条通量推导", 2.0, minimum_defect_deduction=1.0),
            _frontier_math_point(
                20, 2,
                "构造不封闭曲面的直接参数化，正确给出参数域、切向量、侧面外法向和面积元",
                3.0, critical=True, mandatory=True, minimum_defect_deduction=1.5,
            ),
            _frontier_math_point(
                20, 3,
                "利用圆周一、二阶矩独立积分任意 M,c，得到 2πH²[H(tr(M)/3-eᵀMe)-c·e]",
                3.5, critical=True, mandatory=True, depends_on=["q20.f2"],
                minimum_defect_deduction=2.0,
            ),
            _frontier_math_point(20, 4, "从通式给出通量为零的充要条件，量纲与方向约定一致", 1.0, depends_on=["q20.f3"]),
            _frontier_math_point(20, 5, "代入题目给定的 H、M、c，并独立核验精确数值通量", 0.5, depends_on=["q20.f3"]),
            _frontier_math_point(20, 6, "对椭圆锥正确计算体积、顶面面积与顶面线性场积分，得到 πabH² 倍通式", 3.0, mandatory=True, minimum_defect_deduction=1.5),
            _frontier_math_point(20, 7, "用 r=s(e+a cosθu+b sinθv) 直接参数化侧面并计算有向面积元，独立复现通式", 4.0, critical=True, mandatory=True, depends_on=["q20.f6"], minimum_defect_deduction=2.0),
            _frontier_math_point(20, 8, "证明仿射场下结果与椭圆在 e⊥ 内取向无关，并核验 a=b=√2 的退化因子", 3.0, critical=True, mandatory=True, depends_on=["q20.f6", "q20.f7"], minimum_defect_deduction=1.5),
            _frontier_math_point(20, 9, "由两个同轴整锥通量作差，推导 πab[A(H³-L³)-(c·e)(H²-L²)] 并解释上下底面方向", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(20, 10, "在 s∈[L,H] 上直接参数化截锥侧面，独立复现通式而非引用作差结果", 3.0, mandatory=True, depends_on=["q20.f9"], minimum_defect_deduction=1.5),
            _frontier_math_point(20, 11, "代入隐藏 H,M,c 与 a=2,b=1,L=1，给出精确 frustum_flux 并与 L→0 退化交叉核验", 3.0, critical=True, mandatory=True, depends_on=["q20.f9"], minimum_defect_deduction=1.5),
        ],
    },
    21: {
        "instruction": (
            "Frontier 扩展：在 a=3 时进一步求 A 的最小多项式和 Jordan 块类型，并用 "
            "rank(A-I) 与 (A-I)²=0 证明，不得只写特征值。最终 JSON 额外包含 "
            "minimal_polynomial、jordan_type 和 centralizer_dimension。再取 "
            "P=[(1,1,1)^T,(0,0,1/2)^T,(1,-1,0)^T]，在此基下求出全部与 A 对易的"
            "实矩阵 X，并由 X²=P⁻¹AP 完整分类 A 的所有实平方根；必须包含两个孤立主平方根"
            "和异号分支的连续族，最后转换为 B=PXP⁻¹，不得只写 ±(I+(A-I)/2)。"
            "压力层：再完整分类 A² 的所有实平方根。证明其解集恰有多少个连通分支，"
            "分别给出各分支上 determinant 与 trace 的取值，并判定哪些平方根能写成 A 的实多项式。"
            "审计“矩阵只有正特征值，所以每个实平方根都是 A 的多项式”这一说法，并给出明确反例参数。"
            "最终 JSON 还须包含 root_target_power、root_component_count、polynomial_root_count 和 "
            "isolated_nilpotent_coefficient，其中孤立根写成 ±(I+c(A-I))。"
        ),
        "anchors": {
            "minimal_polynomial": {
                "kind": "expression",
                "expected": "(t-1)**2",
                "variables": ["t"],
                "weight": 1,
            },
            "jordan_type": {
                "kind": "literal",
                "expected": "J2(1)+J1(1)",
                "accepted": ["J_2(1)⊕J_1(1)", "J2(1)⊕J1(1)"],
                "weight": 1,
            },
            "centralizer_dimension": {"kind": "expression", "expected": "5", "variables": [], "weight": 1},
            "root_target_power": {"kind": "expression", "expected": "2", "variables": [], "weight": 1},
            "root_component_count": {"kind": "expression", "expected": "4", "variables": [], "weight": 1},
            "polynomial_root_count": {"kind": "expression", "expected": "2", "variables": [], "weight": 1},
            "isolated_nilpotent_coefficient": {"kind": "expression", "expected": "1", "variables": [], "weight": 1},
        },
        "reference": (
            "m_A(t)=(t-1)^2，Jordan 类型 J2(1)⊕J1(1)。在 P 基下 J=I+E12，"
            "其中心化子为 X=[[p,q,r],[0,p,0],[0,s,t]]，维数 5。X²=J："
            "若 t=p=±1，则 r=s=0,q=p/2；若 t=-p,p=±1，则 r,s 任意且 "
            "q=(1-rs)/(2p)。全部平方根为 B=PXP^-1。对 A^k，将 1 替换为 k："
            "同号孤立根为 ±(I+k(A-I)/2)，异号族满足 q=(k-rs)/(2p)。"
            "每个 k>0 均有两个孤立点和两个 R² 连通族，共 4 个连通分支；仅两个孤立根是 A 的多项式。"
        ),
        "points": [
            _frontier_math_point(21, 1, "在 a=3 时计算并证明 (A-I)²=0 且 A≠I", 3.0),
            _frontier_math_point(21, 2, "由此得到最小多项式 (t-1)²", 2.0, critical=True, depends_on=["q21.f1"]),
            _frontier_math_point(21, 3, "计算 rank(A-I)=1，并将其与 Jordan 块数量和大小联系", 2.0, depends_on=["q21.f1"]),
            _frontier_math_point(21, 4, "完整得出 J2(1)⊕J1(1)，维数与几何重数核验一致", 3.0, critical=True, depends_on=["q21.f3"]),
            _frontier_math_point(21, 5, "核验给定 P 的 Jordan 链并直接解 XJ=JX，得到五维中心化子的一般形", 3.0, mandatory=True, minimum_defect_deduction=1.5),
            _frontier_math_point(21, 6, "利用 B²=A 自动推出 BA=AB，再在中心化子中无遗漏地解 X²=J 的同号与异号分支", 4.0, critical=True, mandatory=True, depends_on=["q21.f5"], minimum_defect_deduction=2.0),
            _frontier_math_point(21, 7, "明确两个主平方根和异号连续族的参数条件，并以 B=PXP⁻¹ 给出原坐标完整分类", 3.0, critical=True, mandatory=True, depends_on=["q21.f6"], minimum_defect_deduction=1.5),
            _frontier_math_point(21, 8, "从 A^k=I+k(A-I) 出发，在中心化子中无遗漏地分类隐藏 k 对应的全部实平方根", 4.0, critical=True, mandatory=True, depends_on=["q21.f5"], minimum_defect_deduction=2.0),
            _frontier_math_point(21, 9, "证明两个孤立点与两个 R² 参数族恰为四个连通分支，并用 trace/determinant 排除分支相交", 3.0, mandatory=True, depends_on=["q21.f8"], minimum_defect_deduction=1.5),
            _frontier_math_point(21, 10, "证明仅同号孤立根是 A 的多项式，并从异号族给出可直接代回的非多项式平方根反例", 3.0, critical=True, mandatory=True, depends_on=["q21.f8"], minimum_defect_deduction=1.5),
        ],
    },
    22: {
        "instruction": (
            "Frontier 参数分类：把密度推广为 f_α(x)=α·100^α/(100+x)^(α+1)（x>0，α>0），"
            "免赔额仍为 100，N 仍服从 Poisson(8)，一年总赔付 S=Σ_{i=1}^N Y_i。"
            "分类所有 α 下 E[S]、Var(S) 何时有限；在有限区间给出精确公式；审计“索赔次数"
            "服从泊松分布就能保证年度总赔付方差有限”这一说法。必须从 Y 的尾分布和尾积分"
            "完成矩判定，不能直接套用未核验有限矩公式。最后计算 α=3。进一步证明复合泊松"
            "总赔付满足一大跳渐近 P(S>x)~8P(Y>x)，不能只引用“重尾所以成立”；由此求 "
            "x→∞ 的精确尾常数、p→1 时 VaR_p 的一阶等价式，并在 α>1 时求平均超额损失"
            "E[S-x|S>x] 的一阶等价式。最终 JSON 额外包含 alpha_case_mean、"
            "alpha_case_variance 和 alpha_case_tail_constant。"
            "压力层：在本次数值 α>2 的情形继续求二阶尾展开。不得只引用二阶次指数分布定理；"
            "先对固定 n 证明卷积尾的二阶项，再给出 Poisson 求和的可控截断，从而求精确常数 C2，使"
            "P(S>x)=λ·100^α·x^(-α)+C2·x^(-α-1)+o(x^(-α-1))，其中本题 λ=8。"
            "推导时必须同时计入 (x+200)^(-α) 自身的平移修正和其他赔款的均值位移，"
            "并说明为何两个大跳项在 α>2 时低于所保留阶。最终 JSON 还须包含 "
            "second_order_tail_coefficient。"
        ),
        "anchors": {
            "alpha_case_mean": {
                "kind": "expression",
                "expected": "100",
                "variables": [],
                "weight": 1,
            },
            "alpha_case_variance": {
                "kind": "expression",
                "expected": "40000",
                "variables": [],
                "weight": 1,
            },
            "alpha_case_tail_constant": {"kind": "expression", "expected": "8000000", "variables": [], "weight": 1},
            "second_order_tail_coefficient": {"kind": "expression", "expected": "-2400000000", "variables": [], "weight": 1},
        },
        "reference": (
            "P(Y>y)=(100/(200+y))^α；E[S] 有限当且仅当 α>1，Var(S) 有限当且仅当 α>2。"
            "E[Y]=100^α·200^(1-α)/(α-1)，E[Y²]=2·100^α·200^(2-α)/[(α-1)(α-2)]；"
            "E[S]=8E[Y]，Var(S)=8E[Y²]。α=3 时 E[S]=100，Var(S)=40000。"
            "且 P(S>x)~8·100^αx^-α，VaR_p~[8·100^α/(1-p)]^(1/α)，"
            "α>1 时 E[S-x|S>x]~x/(α-1)；α=3 尾常数为 8,000,000。"
            "一般 λ 且 α>2 时，C2=αλ100^α(λE[Y]-200)。α=3,λ=8,E[Y]=12.5，"
            "故 C2=-2,400,000,000。"
        ),
        "points": [
            _frontier_math_point(
                22, 1,
                "从给定密度推导 P(Y>y)=(100/(200+y))^α（y≥0），边界与无赔付质量处理正确",
                2.0, mandatory=True, minimum_defect_deduction=1.0,
            ),
            _frontier_math_point(
                22, 2,
                "用 Y 的尾积分分类一、二阶矩收敛性，并在 α>1、α>2 时分别导出两个精确矩公式",
                4.0, critical=True, mandatory=True, depends_on=["q22.f1"],
                minimum_defect_deduction=2.0,
            ),
            _frontier_math_point(
                22, 3,
                "由条件期望/方差严格推出复合泊松均值和方差公式，并指出泊松计数不能挽救发散的赔付矩",
                2.0, critical=True, mandatory=True, depends_on=["q22.f2"],
                minimum_defect_deduction=1.0,
            ),
            _frontier_math_point(22, 4, "代入题目指定的 α 得到两个精确数值，并与有限性分类相符", 2.0, depends_on=["q22.f2", "q22.f3"]),
            _frontier_math_point(22, 5, "从固定 n 卷积尾渐近和泊松尾截断控制证明一大跳原理，而非直接引用结论", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(22, 6, "由正则变换尾精确推出 P(S>x) 的常数与 VaR_p 一阶等价式", 3.0, mandatory=True, depends_on=["q22.f5"], minimum_defect_deduction=1.5),
            _frontier_math_point(22, 7, "用尾积分/Karamata 等价的自足推导得到平均超额损失 x/(α-1)，并说明 α≤1 情形", 3.0, critical=True, mandatory=True, depends_on=["q22.f5"], minimum_defect_deduction=1.5),
            _frontier_math_point(22, 8, "对固定 n 自足推导 nF̄(x)+n(n-1)E[Y]α100^αx^(-α-1) 的卷积尾二阶展开并控制双大跳区域", 4.0, critical=True, mandatory=True, minimum_defect_deduction=2.0),
            _frontier_math_point(22, 9, "用 Poisson 阶乘矩和截断控制完成求和，同时计入尾函数平移项，得到 C2=αλ100^α(λE[Y]-200)", 4.0, critical=True, mandatory=True, depends_on=["q22.f8"], minimum_defect_deduction=2.0),
            _frontier_math_point(22, 10, "代入隐藏 α、λ 得到精确二阶常数，并核验阶数、符号与量纲", 2.0, mandatory=True, depends_on=["q22.f9"], minimum_defect_deduction=1.0),
        ],
    },
}


# Only the selected prompt and deterministic answer anchors are materialized at run
# time.  Keeping the pool private prevents catalog browsing from revealing all
# parameter instances while the committed per-run seed makes pause/resume and
# rejudging bit-for-bit reproducible.
MATH_FRONTIER_VARIANTS: dict[int, list[dict[str, Any]]] = {
    17: [
        {
            "variant_id": "stieltjes-shift-1",
            "instruction_replacements": [],
            "anchors": {"extension_answer": MATH_FRONTIER_EXTENSIONS[17]["anchors"]["extension_answer"]},
            "reference": MATH_FRONTIER_EXTENSIONS[17]["reference"],
        },
        {
            "variant_id": "stieltjes-shift-2",
            "instruction_replacements": [
                {
                    "old": "再计算 K=∫_0^1 x^2/[(x+1)(x^2-2x+2)] dx。",
                    "new": "再计算 K=∫_0^1 x^2/[(x+2)(x^2-2x+2)] dx。",
                }
            ],
            "anchors": {
                "extension_answer": {
                    "kind": "expression",
                    "expected": "-7*log(2)/10+pi/20+2*log(3)/5",
                    "variables": [],
                    "weight": 1,
                }
            },
            "reference": (
                "K=-7ln2/10+π/20+2ln3/5；" + MATH_FRONTIER_EXTENSIONS[17]["reference"].split("；", 1)[1]
            ),
        },
        {
            "variant_id": "stieltjes-shift-3",
            "instruction_replacements": [
                {
                    "old": "再计算 K=∫_0^1 x^2/[(x+1)(x^2-2x+2)] dx。",
                    "new": "再计算 K=∫_0^1 x^2/[(x+3)(x^2-2x+2)] dx。",
                }
            ],
            "anchors": {
                "extension_answer": {
                    "kind": "expression",
                    "expected": "-9*log(3)/17+pi/34+14*log(2)/17",
                    "variables": [],
                    "weight": 1,
                }
            },
            "reference": (
                "K=-9ln3/17+π/34+14ln2/17；" + MATH_FRONTIER_EXTENSIONS[17]["reference"].split("；", 1)[1]
            ),
        },
    ],
    18: [
        {
            "variant_id": "anisotropic-rho-half",
            "instruction_replacements": [],
            "anchors": {
                key: MATH_FRONTIER_EXTENSIONS[18]["anchors"][key]
                for key in (
                    "anisotropic_rho",
                    "anisotropic_scale",
                    "anisotropic_base_angle",
                    "anisotropic_lambda1_x_coeff",
                )
            },
            "reference": MATH_FRONTIER_EXTENSIONS[18]["reference"],
        },
        {
            "variant_id": "anisotropic-rho-minus-half",
            "instruction_replacements": [
                {"old": "本次参数为 ρ=1/2", "new": "本次参数为 ρ=-1/2"}
            ],
            "anchors": {
                "anisotropic_rho": {"kind": "expression", "expected": "-1/2", "variables": [], "weight": 1},
                "anisotropic_scale": {"kind": "expression", "expected": "4*sqrt(3)", "variables": [], "weight": 1},
                "anisotropic_base_angle": {"kind": "expression", "expected": "pi/3", "variables": [], "weight": 1},
                "anisotropic_lambda1_x_coeff": {"kind": "expression", "expected": "2", "variables": [], "weight": 1},
            },
            "reference": (
                "原齐次与调和分类同基准参考。对 L_ρ 且 ρ=-1/2，λ=0 时 "
                "f=1+4√3[atan((2u+1)/√3)-π/3]；λ=1 时 g=2x-y；一致椭圆性保证唯一。"
            ),
        },
        {
            "variant_id": "anisotropic-rho-third",
            "instruction_replacements": [
                {"old": "本次参数为 ρ=1/2", "new": "本次参数为 ρ=1/3"}
            ],
            "anchors": {
                "anisotropic_rho": {"kind": "expression", "expected": "1/3", "variables": [], "weight": 1},
                "anisotropic_scale": {"kind": "expression", "expected": "2*sqrt(2)", "variables": [], "weight": 1},
                "anisotropic_base_angle": {"kind": "expression", "expected": "atan(1/sqrt(2))", "variables": [], "weight": 1},
                "anisotropic_lambda1_x_coeff": {"kind": "expression", "expected": "2", "variables": [], "weight": 1},
            },
            "reference": (
                "原齐次与调和分类同基准参考。对 L_ρ 且 ρ=1/3，λ=0 时 "
                "f=1+2√2[atan((3u-1)/(2√2))-atan(1/√2)]；λ=1 时 g=2x-y；一致椭圆性保证唯一。"
            ),
        },
    ],
    19: [
        {
            "variant_id": "quartic-p1-q3",
            "instruction_replacements": [],
            "anchors": {
                "explicit_kappa_max": MATH_FRONTIER_EXTENSIONS[19]["anchors"]["explicit_kappa_max"]
            },
            "reference": MATH_FRONTIER_EXTENSIONS[19]["reference"],
        },
        {
            "variant_id": "quartic-p2-q4",
            "instruction_replacements": [
                {
                    "old": "f(x)=x^4+x^3+3x²",
                    "new": "f(x)=x^4+2x^3+4x²",
                }
            ],
            "anchors": {
                "explicit_kappa_max": {"kind": "expression", "expected": "5/2", "variables": [], "weight": 1}
            },
            "reference": (
                "一般等价与固定步长反例同基准参考。对 x^4+2x^3+4x²，"
                "f''=12x²+12x+8 在 x=-1/2 取最小值 5，故 κ_max=5/2。"
            ),
        },
        {
            "variant_id": "quartic-pminus1-q5",
            "instruction_replacements": [
                {
                    "old": "f(x)=x^4+x^3+3x²",
                    "new": "f(x)=x^4-x^3+5x²",
                }
            ],
            "anchors": {
                "explicit_kappa_max": {"kind": "expression", "expected": "37/8", "variables": [], "weight": 1}
            },
            "reference": (
                "一般等价与固定步长反例同基准参考。对 x^4-x^3+5x²，"
                "f''=12x²-6x+10 在 x=1/4 取最小值 37/4，故 κ_max=37/8。"
            ),
        },
    ],
    20: [
        {
            "variant_id": "affine-h2-a",
            "instruction_replacements": [],
            "anchors": MATH_FRONTIER_EXTENSIONS[20]["anchors"],
            "reference": MATH_FRONTIER_EXTENSIONS[20]["reference"],
        },
        {
            "variant_id": "affine-h3-b",
            "instruction_replacements": [
                {
                    "old": (
                        "最后取 H=2，M=[[1,2,0],[0,-1,3],[4,0,2]]，"
                        "c=(1,-2,1) 作数值核验。"
                    ),
                    "new": (
                        "最后取 H=3，M=[[2,0,1],[1,-1,0],[0,3,1]]，"
                        "c=(1,1,1) 作数值核验。"
                    ),
                }
            ],
            "anchors": {
                "affine_flux": {
                    "kind": "expression",
                    "expected": "-90*pi-18*sqrt(3)*pi",
                    "variables": [],
                    "weight": 1,
                },
                "frustum_flux": {
                    "kind": "expression",
                    "expected": "-260*pi/3-16*sqrt(3)*pi",
                    "variables": [],
                    "weight": 1,
                },
            },
            "reference": (
                "Φ=2πH²[H(tr(M)/3-eᵀMe)-c·e]；零通量当且仅当 "
                "c·e=H(tr(M)/3-eᵀMe)；给定数据 Φ=-90π-18√3π；椭圆推广为 "
                "πabH²[H(tr(M)/3-eᵀMe)-c·e]，与 u,v 取向无关。"
                "对 a=2,b=1,L=1 的截锥，Φ=-260π/3-16√3π。"
            ),
        },
        {
            "variant_id": "affine-h4-c",
            "instruction_replacements": [
                {
                    "old": (
                        "最后取 H=2，M=[[1,2,0],[0,-1,3],[4,0,2]]，"
                        "c=(1,-2,1) 作数值核验。"
                    ),
                    "new": (
                        "最后取 H=4，M=[[0,1,2],[-2,3,0],[1,0,-1]]，"
                        "c=(3,0,-3) 作数值核验。"
                    ),
                }
            ],
            "anchors": {
                "affine_flux": {
                    "kind": "expression",
                    "expected": "-256*pi/3",
                    "variables": [],
                    "weight": 1,
                },
                "frustum_flux": {
                    "kind": "expression",
                    "expected": "-84*pi",
                    "variables": [],
                    "weight": 1,
                },
            },
            "reference": (
                "Φ=2πH²[H(tr(M)/3-eᵀMe)-c·e]；零通量当且仅当 "
                "c·e=H(tr(M)/3-eᵀMe)；给定数据 Φ=-256π/3；椭圆推广为 "
                "πabH²[H(tr(M)/3-eᵀMe)-c·e]，与 u,v 取向无关。"
                "对 a=2,b=1,L=1 的截锥，Φ=-84π。"
            ),
        },
    ],
    21: [
        {
            "variant_id": "matrix-root-power-2",
            "instruction_replacements": [],
            "anchors": {
                key: MATH_FRONTIER_EXTENSIONS[21]["anchors"][key]
                for key in (
                    "root_target_power",
                    "root_component_count",
                    "polynomial_root_count",
                    "isolated_nilpotent_coefficient",
                )
            },
            "reference": MATH_FRONTIER_EXTENSIONS[21]["reference"],
        },
        {
            "variant_id": "matrix-root-power-3",
            "instruction_replacements": [
                {"old": "完整分类 A² 的所有实平方根", "new": "完整分类 A³ 的所有实平方根"}
            ],
            "anchors": {
                "root_target_power": {"kind": "expression", "expected": "3", "variables": [], "weight": 1},
                "root_component_count": {"kind": "expression", "expected": "4", "variables": [], "weight": 1},
                "polynomial_root_count": {"kind": "expression", "expected": "2", "variables": [], "weight": 1},
                "isolated_nilpotent_coefficient": {"kind": "expression", "expected": "3/2", "variables": [], "weight": 1},
            },
            "reference": (
                "原 A 平方根分类同基准参考。A³=I+3(A-I)；在 P 基下同号孤立根为 "
                "±(I+3E12/2)，异号族 q=(3-rs)/(2p)。解集为两个孤立点与两个 R² 族，"
                "共四个连通分支；仅两个孤立根是 A 的多项式。"
            ),
        },
        {
            "variant_id": "matrix-root-power-5",
            "instruction_replacements": [
                {"old": "完整分类 A² 的所有实平方根", "new": "完整分类 A⁵ 的所有实平方根"}
            ],
            "anchors": {
                "root_target_power": {"kind": "expression", "expected": "5", "variables": [], "weight": 1},
                "root_component_count": {"kind": "expression", "expected": "4", "variables": [], "weight": 1},
                "polynomial_root_count": {"kind": "expression", "expected": "2", "variables": [], "weight": 1},
                "isolated_nilpotent_coefficient": {"kind": "expression", "expected": "5/2", "variables": [], "weight": 1},
            },
            "reference": (
                "原 A 平方根分类同基准参考。A⁵=I+5(A-I)；在 P 基下同号孤立根为 "
                "±(I+5E12/2)，异号族 q=(5-rs)/(2p)。解集为两个孤立点与两个 R² 族，"
                "共四个连通分支；仅两个孤立根是 A 的多项式。"
            ),
        },
    ],
    22: [
        {
            "variant_id": "pareto-alpha-3",
            "instruction_replacements": [],
            "anchors": MATH_FRONTIER_EXTENSIONS[22]["anchors"],
            "reference": MATH_FRONTIER_EXTENSIONS[22]["reference"],
        },
        {
            "variant_id": "pareto-alpha-4-lambda-5",
            "instruction_replacements": [
                {"old": "N 仍服从 Poisson(8)", "new": "N 仍服从 Poisson(5)"},
                {"old": "最后计算 α=3。", "new": "最后计算 α=4。"},
                {
                    "old": "满足一大跳渐近 P(S>x)~8P(Y>x)",
                    "new": "满足一大跳渐近 P(S>x)~5P(Y>x)",
                },
                {"old": "其中本题 λ=8", "new": "其中本题 λ=5"},
            ],
            "anchors": {
                "alpha_case_mean": {
                    "kind": "expression",
                    "expected": "125/6",
                    "variables": [],
                    "weight": 1,
                },
                "alpha_case_variance": {
                    "kind": "expression",
                    "expected": "12500/3",
                    "variables": [],
                    "weight": 1,
                },
                "alpha_case_tail_constant": {
                    "kind": "expression",
                    "expected": "500000000",
                    "variables": [],
                    "weight": 1,
                },
                "second_order_tail_coefficient": {
                    "kind": "expression",
                    "expected": "-1075000000000/3",
                    "variables": [],
                    "weight": 1,
                },
            },
            "reference": (
                "P(Y>y)=(100/(200+y))^α；E[S] 有限当且仅当 α>1，Var(S) 有限当且仅当 α>2。"
                "E[Y]=100^α·200^(1-α)/(α-1)，E[Y²]=2·100^α·200^(2-α)/[(α-1)(α-2)]；"
                "E[S]=5E[Y]，Var(S)=5E[Y²]。α=4 时 E[S]=125/6，Var(S)=12500/3。"
                "P(S>x)~5·100^αx^-α，VaR_p~[5·100^α/(1-p)]^(1/α)，平均超额损失~x/(α-1)；"
                "α=4 尾常数 500000000。二阶 C2=αλ100^α(λE[Y]-200)=-1075000000000/3。"
            ),
        },
        {
            "variant_id": "pareto-alpha-5-lambda-12",
            "instruction_replacements": [
                {"old": "N 仍服从 Poisson(8)", "new": "N 仍服从 Poisson(12)"},
                {"old": "最后计算 α=3。", "new": "最后计算 α=5。"},
                {
                    "old": "满足一大跳渐近 P(S>x)~8P(Y>x)",
                    "new": "满足一大跳渐近 P(S>x)~12P(Y>x)",
                },
                {"old": "其中本题 λ=8", "new": "其中本题 λ=12"},
            ],
            "anchors": {
                "alpha_case_mean": {
                    "kind": "expression",
                    "expected": "75/4",
                    "variables": [],
                    "weight": 1,
                },
                "alpha_case_variance": {
                    "kind": "expression",
                    "expected": "2500",
                    "variables": [],
                    "weight": 1,
                },
                "alpha_case_tail_constant": {
                    "kind": "expression",
                    "expected": "120000000000",
                    "variables": [],
                    "weight": 1,
                },
                "second_order_tail_coefficient": {
                    "kind": "expression",
                    "expected": "-108750000000000",
                    "variables": [],
                    "weight": 1,
                },
            },
            "reference": (
                "P(Y>y)=(100/(200+y))^α；E[S] 有限当且仅当 α>1，Var(S) 有限当且仅当 α>2。"
                "E[Y]=100^α·200^(1-α)/(α-1)，E[Y²]=2·100^α·200^(2-α)/[(α-1)(α-2)]；"
                "E[S]=12E[Y]，Var(S)=12E[Y²]。α=5 时 E[S]=75/4，Var(S)=2500。"
                "P(S>x)~12·100^αx^-α，VaR_p~[12·100^α/(1-p)]^(1/α)，平均超额损失~x/(α-1)；"
                "α=5 尾常数 120000000000。二阶 C2=αλ100^α(λE[Y]-200)=-108750000000000。"
            ),
        },
    ],
}


def build_frontier_math_cases() -> list[dict[str, Any]]:
    """Turn six mature exam questions into seeded, closed-book three-layer probes."""

    originals = build_builtin_math_cases()["tool-augmented"][16:22]
    output: list[dict[str, Any]] = []
    for number, item in zip(range(17, 23), originals, strict=True):
        definition = copy.deepcopy(item["definition"])
        extension = MATH_FRONTIER_EXTENSIONS[number]
        definition["slug"] = f"sixdim.math.frontier.q{number}"
        definition["version"] = SUITE_VERSION
        definition["title"] = f"数学推理 Frontier · 第 {number} 题三层压力测试"
        definition["description"] = "2025 数学一原题、Frontier 证明扩展与隐藏变参压力层；确定性锚点和三裁判联合闭卷评分。"
        definition["instruction"] = (
            definition["instruction"].replace(
                "2025 年考研数学（一）工具增强测试",
                "六维能力闭卷极限测试",
            )
            + "\n\n"
            + str(extension["instruction"])
            + "\n必须同时完成原题与 Frontier 扩展，推导中不得把数值软件输出当作证明。"
        )
        definition["tools"] = []
        definition["limits"] = {
            "max_steps": 160,
            "time_target_seconds": 3600,
            "max_runtime_seconds": 7200,
            "token_budget": 150000,
        }
        symbolic = next(
            (validator for validator in definition["validators"] if validator["type"] == "symbolic_json"),
            None,
        )
        if extension["anchors"]:
            if symbolic is None:
                symbolic = {
                    "type": "symbolic_json",
                    "weight": 40,
                    "config": {"fields": {}},
                }
                definition["validators"].insert(0, symbolic)
            symbolic["config"]["fields"].update(copy.deepcopy(extension["anchors"]))
        if symbolic is not None:
            symbolic["weight"] = 40
            symbolic["config"].update(
                {
                    "score_cap_on_failure": 70,
                    "score_cap_threshold": 100,
                    "score_cap_key": "frontier_math_anchor_failed",
                    "score_cap_reason": "原题、Frontier 扩展或隐藏压力层的确定性答案锚点缺失或错误",
                }
            )
        rubric_validator = next(
            validator for validator in definition["validators"] if validator["type"] == "ai_rubric"
        )
        rubric_validator["weight"] = 60
        rubric = rubric_validator["config"]
        original_reference = str(rubric.get("reference_answer") or "")
        original_obligations = copy.deepcopy(rubric.get("solution_obligations") or [])
        for point in rubric["scoring_points"]:
            point.setdefault("mandatory", False)
            point.setdefault("minimum_defect_deduction", 1.0)
        if number == 19:
            for point in rubric["scoring_points"]:
                if point["point_id"] == "q19.2":
                    point["description"] = (
                        "充分性：取单侧极限先得到 f'(s)≤f'(t)，不得把严格割线不等式直接保留为严格导数不等式"
                    )
                    point["critical"] = True
                    point["mandatory"] = True
                    point["minimum_defect_deduction"] = 1.5
        rubric["scoring_points"].extend(copy.deepcopy(extension["points"]))
        rubric["solution_obligations"].append(str(extension["instruction"]))
        rubric["reference_answer"] = (
            str(rubric.get("reference_answer") or "") + "；" + str(extension["reference"])
        )
        rubric["max_points"] = sum(
            float(point["max_points"]) for point in rubric["scoring_points"]
        )
        rubric["question_points"] = rubric["max_points"]
        rubric["rubric_version"] = f"sixdim.math.frontier.q{number}.v5"
        rubric["full_credit_confidence"] = 0.95
        rubric["required_judges"] = 3
        rubric["judge_disagreement_threshold"] = 2.0
        rubric["consensus_mode"] = "defect_aware"
        rubric["critical_failure_score_cap"] = 60.0
        rubric["mandatory_failure_score_cap"] = 80.0
        rubric["critical_defect_score_cap"] = 88.0
        required_result_fields = list(symbolic["config"]["fields"]) if symbolic else []
        definition["instruction"] += (
            "\n最终交付必须是单个、可解析的 JSON 对象，不得放在 Markdown 代码块外；"
            "solution 必须包含完整证明。除 solution 外必须逐项给出这些结果字段："
            + "、".join(required_result_fields)
            + "。字段缺失、类型错误或仅在 solution 文本中提及，均视为确定性结果未提交。"
        )
        variants = MATH_FRONTIER_VARIANTS.get(number) or []
        if variants:
            materialized_variants: list[dict[str, Any]] = []
            for variant in variants:
                variant_instruction = definition["instruction"]
                variant_obligation = str(extension["instruction"])
                for replacement in variant.get("instruction_replacements") or []:
                    old = str(replacement["old"])
                    if old not in variant_instruction:
                        raise ValueError(
                            f"frontier_variant_replacement_missing:q{number}:{variant['variant_id']}"
                        )
                    variant_instruction = variant_instruction.replace(
                        old, str(replacement["new"]), 1
                    )
                    if old in variant_obligation:
                        variant_obligation = variant_obligation.replace(
                            old, str(replacement["new"]), 1
                        )
                materialized_variants.append(
                    {
                        "variant_id": variant["variant_id"],
                        "instruction": variant_instruction,
                        "validator_config_overrides": [
                            {
                                "type": "symbolic_json",
                                "config": {"fields": copy.deepcopy(variant["anchors"])},
                            },
                            {
                                "type": "ai_rubric",
                                "config": {
                                    "reference_answer": (
                                        original_reference + "；" + str(variant["reference"])
                                    ),
                                    "solution_obligations": [
                                        *copy.deepcopy(original_obligations),
                                        variant_obligation,
                                    ],
                                },
                            },
                        ],
                    }
                )
            definition["_private_frontier_variants"] = {
                "schema": "agentbench.frontier-variants/v1",
                "pool_version": f"sixdim.math.frontier.q{number}.pool-v3",
                "variants": materialized_variants,
            }
        definition["tags"] = [
            "six-dimension",
            "frontier-math",
            "closed-book",
            "proof-audit",
            "multi-layer",
        ]
        definition["metadata"].update(
            {
                "difficulty": 6,
                "tier": "frontier",
                "lane": "frontier-closed-book",
                "estimated_minutes": 60,
                "score_basis": "quality_only",
                "mastery_curve": "frontier_v1",
                "frontier_profile": "seeded-three-layer-proof-v5",
                "rubric_version": rubric["rubric_version"],
            }
        )
        output.append(definition)
    return output


def build_six_dimension_cases() -> list[dict[str, Any]]:
    return [
        _frontend_case(
            "sixdim.frontend-self-digital-experience",
            "创意前端 Ultra · 关于模型自己的数字体验",
            FRONTEND_SELF_PROMPT,
            "self",
            180,
        ),
        _frontend_case(
            "sixdim.frontend-hong-kong-voxel",
            "创意前端 Ultra · 香港维港体素数字沙盘",
            FRONTEND_HONG_KONG_PROMPT,
            "hong-kong",
            240,
        ),
        _frontend_case(
            "sixdim.frontend-single-file-black-hole",
            "创意前端 Ultra · 单文件黑洞视觉奇观",
            FRONTEND_BLACK_HOLE_PROMPT,
            "black-hole",
            120,
        ),
        _research_case(
            "sixdim.research-heliogrid-acquisition",
            "研究写作 Ultra · HelioGrid 并购决策备忘录",
            "你是收购方董事会独立研究负责人。判断是否应按卖方条件收购 HelioGrid，并给出最高可接受估值与签约前置条件。",
            RESEARCH_SOURCES_1,
            90,
        ),
        _research_case(
            "sixdim.research-urban-heat-policy",
            "研究写作 Ultra · 城市热风险组合政策",
            "你是市政府首席证据官。用五年 4,000 万元预算设计热风险干预组合，说明资金分配、效果预测、公平性和停止/扩张规则。",
            RESEARCH_SOURCES_2,
            90,
        ),
        *build_data_frontier_cases(),
        *build_frontier_math_cases(),
        build_moment_transfer_case(),
    ]


SUITE_CASE_SLUGS: tuple[str, ...] = (
    "sixdim.frontend-self-digital-experience",
    "sixdim.frontend-hong-kong-voxel",
    "sixdim.frontend-single-file-black-hole",
    "ultra.strong-consistency-financial-ledger-001",
    "ultra.distributed-task-queue-001",
    "sixdim.math.frontier.q17",
    "sixdim.math.frontier.q18",
    "sixdim.math.frontier.q19",
    "sixdim.math.frontier.q20",
    "sixdim.math.frontier.q21",
    "sixdim.math.frontier.q22",
    "sixdim.math.moment-duality-transfer",
    "sixdim.research-heliogrid-acquisition",
    "sixdim.research-urban-heat-policy",
    "sixdim.data-incremental-revenue-ledger",
    "sixdim.data-online-experiment-audit",
    "sixdim.data-temporal-risk-model",
    "ultra.event-store-crash-consistency-003",
    "ultra.hidden-general-resource-scheduler-003",
)


__all__ = [
    "DIMENSIONS",
    "DIMENSION_BY_KEY",
    "SUITE_CASE_SLUGS",
    "SUITE_VERSION",
    "build_frontier_math_cases",
    "build_six_dimension_cases",
]
