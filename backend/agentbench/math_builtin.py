from __future__ import annotations

from typing import Any

from .math_exam import MATH_EXAM_ID, build_published_math_cases

SOURCE_FILENAME = "ab27a44c5f0cbe5e.pdf"
SOURCE_SHA256 = "9ebd0eebbbfeef553880cb13af3528bbbb25630b86d7ed22fb5f9c85b0c659bf"
SOURCE_PAGE_COUNT = 17
RUBRIC_VERSION = "2025.math1.solution.strict-exam.v4"
RUBRIC_SOURCE = {
    "source_id": "moe-policy-2025-plus-expert-reconstruction",
    "version": RUBRIC_VERSION,
    "source_tier": "expert_reconstructed",
    "title": "2025 年考研数学（一）解答题严格专家重建评分量表",
    "issuing_body": "AgentBench 专家重建；评卷制度依据为教育部、教育部教育考试院",
    "url": "https://www.gov.cn/zhengce/zhengceku/202410/content_6978684.htm",
    "accessed_at": "2026-08-26",
    "page": "第七条、第四十条、第四十二条",
    "evidence": "教育部规定全国统一命题科目由教育部教育考试院提供评分参考，省级专家组经试评拟定具体评卷细则；评分参考（指南）按国家秘密管理。公开来源未发现可核验的2025数学一逐题官方分值细则。",
    "verification_status": "partially_verified",
    "notes": "官方条文仅证明评卷制度与来源链；逐题评分点由参考解答按踩点给分原则重建。解答题卷面分值按数学一正式题型结构分配为10、10、10、10、15、15。严格制采用0.5分粒度、逻辑缺口强制扣分和至少双匿名裁判，不宣称为官方逐题评分参考。",
}
Q20_RUBRIC_VERSION = "2025.math1.solution.q20.corrected.strict-v5"
Q20_RUBRIC_SOURCE = {
    **RUBRIC_SOURCE,
    "version": Q20_RUBRIC_VERSION,
    "source_id": "2025-math1-q20-double-derived-correction",
    "verification_status": "partially_verified",
    "evidence": (
        "第20题以高斯公式和直接参数化两条独立解析路线复核：旋转面为 "
        "xy+yz+zx=0，截面半径平方为2/3，侧面通量为-2π/√3；修正旧重建值。"
    ),
    "notes": "本题逐点量表为专家重建；v2 修正了 v1 的参考答案与末评分点。",
}


def _question(
    number: int,
    kind: str,
    points: int,
    text: str,
    answer: str,
    pages: list[int],
    *,
    accepted: list[str] | None = None,
    variables: list[str] | None = None,
    obligations: list[str] | None = None,
    mark_values: list[float] | None = None,
    answer_kind: str = "expression",
    objective_weight: int = 40,
    rubric_version: str | None = None,
    rubric_source: dict[str, Any] | None = None,
    source_tier: str = "unverified",
    scoring_points: list[dict[str, Any]] | None = None,
    alternate_paths: list[dict[str, Any]] | None = None,
    allow_new_solutions: bool = True,
    low_confidence_threshold: float = 0.75,
    judge_disagreement_threshold: float = 4.0,
    marking_mode: str = "strict_exam",
    point_increment: float = 0.5,
    minor_defect_deduction: float = 0.5,
    major_defect_deduction: float = 1.0,
    full_credit_confidence: float = 0.90,
    required_judges: int = 2,
    critical_failure_score_cap: float = 60.0,
    answer_anchor_fields: dict[str, Any] | None = None,
    answer_anchor_failure_cap: float = 60.0,
) -> dict[str, Any]:
    obligations = obligations or []
    if mark_values is not None and len(mark_values) != len(obligations):
        raise ValueError(f"question_{number}_mark_values_must_match_obligations")
    generated_scoring_points = [
        {
            "point_id": f"q{number}.{index}",
            "description": obligation,
            "max_points": mark_values[index - 1],
            "depends_on": [],
            "mutually_exclusive_with": [],
            "alternate_for": [],
            "error_carry_forward": {
                "enabled": True,
                "rule": "前一步独立错误导致的后续机械结果不重复扣分；后续方法正确时保留相应方法分。",
                "independent_work_credit": True,
                "max_repeated_deduction": 0,
            },
            "evidence_required": ["考生作答中的对应公式、推导或结论"],
        }
        for index, obligation in enumerate(obligations, 1)
    ] if mark_values is not None else []
    effective_scoring_points = scoring_points if scoring_points is not None else generated_scoring_points
    effective_version = rubric_version or (RUBRIC_VERSION if effective_scoring_points else None)
    effective_source = rubric_source or (dict(RUBRIC_SOURCE) if effective_scoring_points else None)
    effective_tier = (
        source_tier
        if source_tier != "unverified" or not effective_scoring_points
        else "expert_reconstructed"
    )
    return {
        "number": number,
        "type": kind,
        "points": points,
        "question_text": text.strip(),
        "source_pages": pages,
        "detection_confidence": "verified",
        "answer": answer,
        "accepted_answers": accepted or [],
        "variables": variables or [],
        "solution_obligations": obligations,
        "answer_kind": answer_kind,
        "objective_weight": objective_weight,
        "rubric_version": effective_version,
        "rubric_source": effective_source,
        "source_tier": effective_tier,
        "scoring_points": effective_scoring_points,
        "alternate_paths": alternate_paths or [],
        "allow_new_solutions": allow_new_solutions,
        "low_confidence_threshold": (
            max(low_confidence_threshold, 0.75)
            if effective_scoring_points
            else low_confidence_threshold
        ),
        "judge_disagreement_threshold": judge_disagreement_threshold,
        "marking_mode": marking_mode,
        "point_increment": point_increment,
        "minor_defect_deduction": minor_defect_deduction,
        "major_defect_deduction": major_defect_deduction,
        "full_credit_confidence": full_credit_confidence,
        "required_judges": required_judges,
        "critical_failure_score_cap": critical_failure_score_cap,
        "answer_anchor_fields": answer_anchor_fields or {},
        "answer_anchor_failure_cap": answer_anchor_failure_cap,
        "review_status": "confirmed",
    }


def _point(
    question: int,
    index: int,
    description: str,
    max_points: float,
    *,
    depends_on: list[str] | None = None,
    critical: bool = False,
    carry_forward: bool = False,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Create one strict, evidence-bearing mark instead of a keyword checklist."""

    return {
        "point_id": f"q{question}.{index}",
        "description": description,
        "max_points": max_points,
        "depends_on": depends_on or [],
        "mutually_exclusive_with": [],
        "alternate_for": [],
        "error_carry_forward": {
            "enabled": carry_forward,
            "rule": (
                "仅当前置数值错误被明确继承、且本步机械推导独立正确时保留本步方法分；"
                "不得把缺失推导或独立概念错误标为顺延误差。"
            ),
            "independent_work_credit": carry_forward,
            "max_repeated_deduction": 0,
        },
        "evidence_required": evidence
        or ["必须引用考生作答中的具体公式、代入、定理条件或推理句；只出现关键词不得分"],
        "critical": critical,
    }


BUILTIN_2025_MATH1_QUESTIONS: list[dict[str, Any]] = [
    _question(
        1,
        "choice",
        5,
        r"""
已知函数
f(x)=∫_0^x e^(t^2) sin(t) dt，
g(x)=(∫_0^x e^(t^2) dt) sin^2(x)，则：
A. x=0 是 f(x) 的极值点，也是 g(x) 的极值点。
B. x=0 是 f(x) 的极值点，(0,0) 是曲线 y=g(x) 的拐点。
C. x=0 是 f(x) 的极值点，(0,0) 是曲线 y=f(x) 的拐点。
D. (0,0) 是曲线 y=f(x) 的拐点，(0,0) 也是曲线 y=g(x) 的拐点。
""",
        "B",
        [1],
    ),
    _question(
        2,
        "choice",
        5,
        r"""
已知级数：
① Σ_(n=1)^∞ sin(n^3π/(n^2+1))；
② Σ_(n=1)^∞ (-1)^n [1/∛(n^2)-tan(1/∛(n^2))]。
则：
A. ①与②均条件收敛。
B. ①条件收敛，②绝对收敛。
C. ①绝对收敛，②条件收敛。
D. ①与②均绝对收敛。
""",
        "B",
        [2],
    ),
    _question(
        3,
        "choice",
        5,
        r"""
设函数 f(x) 在区间 (0,+∞) 上可导，则：
A. 当 lim_(x→+∞) f(x) 存在时，lim_(x→+∞) f'(x) 存在。
B. 当 lim_(x→+∞) f'(x) 存在时，lim_(x→+∞) f(x) 存在。
C. 当 lim_(x→+∞) [∫_0^x f(t)dt]/x 存在时，lim_(x→+∞) f(x) 存在。
D. 当 lim_(x→+∞) f(x) 存在时，lim_(x→+∞) [∫_0^x f(t)dt]/x 存在。
""",
        "D",
        [3],
    ),
    _question(
        4,
        "choice",
        5,
        r"""
设函数 f(x,y) 连续，将积分
I=∫_(-2)^2 dx ∫_(4-x^2)^4 f(x,y)dy
改换积分次序。以下哪一项正确？
A. ∫_0^4 [∫_(-2)^(-√(4-y)) f(x,y)dx + ∫_(√(4-y))^2 f(x,y)dx]dy。
B. ∫_0^4 [∫_(-2)^(√(4-y)) f(x,y)dx + ∫_(√(4-y))^2 f(x,y)dx]dy。
C. ∫_0^4 [∫_(-2)^(-√(4-y)) f(x,y)dx + ∫_2^(√(4-y)) f(x,y)dx]dy。
D. 2∫_0^4 dy ∫_(√(4-y))^2 f(x,y)dx。
""",
        "A",
        [3, 4],
    ),
    _question(
        5,
        "choice",
        5,
        "二次型 f(x1,x2,x3)=x1^2+2x1x2+2x1x3 的正惯性指数为：A.0；B.1；C.2；D.3。",
        "B",
        [4, 5],
    ),
    _question(
        6,
        "choice",
        5,
        r"""
设 α1,α2,α3,α4 是 n 维列向量，α1,α2 线性无关，α1,α2,α3 线性相关，且 α1+α2+α4=0。
在空间直角坐标系 O-xyz 中，关于 x,y,z 的方程组 xα1+yα2+zα3=α4 的几何图形是：
A. 过原点的一个平面。
B. 过原点的一条直线。
C. 不过原点的一个平面。
D. 不过原点的一条直线。
""",
        "D",
        [5],
    ),
    _question(
        7,
        "choice",
        5,
        r"""
设 n 阶矩阵 A,B,C 满足 r(A)+r(B)+r(C)=r(ABC)+2n，给出结论：
① r(ABC)+n=r(AB)+r(C)；
② r(AB)+n=r(A)+r(B)；
③ r(A)=r(B)=r(C)=n；
④ r(AB)=r(BC)=n。
其中正确结论的序号是：
A. ①②；B. ①③；C. ②④；D. ③④。
""",
        "A",
        [6],
    ),
    _question(
        8,
        "choice",
        5,
        r"""
设二维随机变量 (X,Y) 服从正态分布 N(0,0;1,1;ρ)，其中 ρ∈(-1,1)。若 a,b 为满足 a^2+b^2=1 的任意实数，则 D(aX+bY) 的最大值为：
A. 1；B. 2；C. 1+|ρ|；D. 1+ρ^2。
""",
        "C",
        [6, 7],
    ),
    _question(
        9,
        "choice",
        5,
        r"""
设 X1,X2,...,X20 是来自总体 B(1,0.1) 的简单随机样本，令 T=Σ_(i=1)^20 Xi。利用泊松分布近似表示二项分布的方法可得 P{T≤1}≈：
A. 1/e^2；B. 2/e^2；C. 3/e^2；D. 4/e^2。
""",
        "C",
        [7],
    ),
    _question(
        10,
        "choice",
        5,
        r"""
设 X1,X2,...,Xn 为来自正态总体 N(μ,2) 的简单随机样本，记 X̄=(1/n)ΣXi，Zα 表示标准正态分布的上侧 α 分位数。
假设检验 H0: μ≤1，H1: μ>1 的显著性水平为 α 的检验，其拒绝域为：
A. X̄>1+(2/n)Zα。
B. X̄>1+(√2/n)Zα。
C. X̄>1+(2/√n)Zα。
D. X̄>1+√(2/n)Zα。
""",
        "D",
        [7, 8],
    ),
    _question(
        11,
        "fill",
        5,
        "计算极限 lim_(x→0+) (x^x-1)/[ln(x)·ln(1-x)]。",
        "-1",
        [8],
    ),
    _question(
        12,
        "fill",
        5,
        r"""
已知函数 f(x)={0, 0≤x<1/2；x^2, 1/2≤x≤1} 的傅里叶级数为 Σ_(n=1)^∞ b_n sin(nπx)，S(x) 为该级数的和函数，求 S(-7/2)。
""",
        "1/8",
        [8],
    ),
    _question(
        13,
        "fill",
        5,
        "已知函数 u(x,y,z)=x y^2 z^3，向量 n=(2,2,-1)，求在点 (1,1,1) 处沿 n 方向的方向导数 ∂u/∂n。",
        "1",
        [8, 9],
    ),
    _question(
        14,
        "fill",
        5,
        r"""
有向曲线 L 是沿抛物线 y=1-x^2 从点 (1,0) 到点 (-1,0) 的一段，求曲线积分
∫_L (y+cos x)dx + (2x+cos y)dy。
""",
        "4/3-2*sin(1)",
        [9],
    ),
    _question(
        15,
        "fill",
        5,
        r"""
设矩阵 A=[[4,2,-3],[a,3,-4],[b,5,-7]]。若方程组 A^2 x=0 与 Ax=0 不同解，求 a-b。
""",
        "-4",
        [9, 10],
    ),
    _question(
        16,
        "fill",
        5,
        r"""
设 A,B 为两个随机事件，且 A 与 B 相互独立。已知 P(A)=2P(B)，P(A∪B)=5/8。在事件 A、B 至少有一个发生的条件下，A、B 中恰有一个发生的概率为多少？
""",
        "4/5",
        [10],
    ),
    _question(
        17,
        "solution",
        10,
        "计算定积分 ∫_0^1 1/[(x+1)(x^2-2x+2)] dx。",
        "3*log(2)/10+pi/10",
        [11],
        obligations=[
            "完成正确的部分分式分解或给出等价积分方法",
            "分别正确处理对数项与反正切项",
            "代入上下限并化简为 3ln2/10+π/10",
        ],
        scoring_points=[
            _point(17, 1, "写出正确部分分式分解，并可由合并分母直接复核", 2.5),
            _point(17, 2, "对数部分的原函数及系数正确", 2.0, depends_on=["q17.1"], carry_forward=True),
            _point(17, 3, "完成平方后反正切部分的原函数、尺度和系数正确", 2.0, depends_on=["q17.1"], carry_forward=True),
            _point(17, 4, "代入 0、1 两端并合并为 3ln2/10+π/10", 3.5, depends_on=["q17.2", "q17.3"], critical=True, carry_forward=True),
        ],
        answer_anchor_fields={
            "final_answer": {
                "kind": "expression",
                "expected": "3*log(2)/10+pi/10",
                "variables": [],
                "weight": 1,
            }
        },
    ),
    _question(
        18,
        "solution",
        10,
        r"""
已知函数 f(u) 在区间 (0,+∞) 内具有 2 阶导数，记 g(x,y)=f(x/y)。若
x^2 g_xx + xy g_xy + y^2 g_yy = 1，
且 g(x,x)=1，g_x(x,x)=2/x，求 f(u)。
""",
        "log(u)**2/2+2*log(u)+1",
        [11, 12],
        variables=["u"],
        obligations=[
            "令 u=x/y 并正确计算所需的一、二阶偏导",
            "把偏微分方程化为 u^2 f''(u)+u f'(u)=1",
            "由 g(x,x)=1 与 g_x(x,x)=2/x 得到 f(1)=1、f'(1)=2",
            "求解常微分方程并得到 f(u)=1/2(ln u)^2+2ln u+1",
        ],
        scoring_points=[
            _point(18, 1, "令 u=x/y，逐项写出并正确计算所需一、二阶偏导", 2.0),
            _point(18, 2, "代回原式并化简为 u²f''(u)+uf'(u)=1", 2.0, depends_on=["q18.1"], critical=True, carry_forward=True),
            _point(18, 3, "从两项边界条件分别推出 f(1)=1、f'(1)=2", 2.0),
            _point(18, 4, "解欧拉型方程并正确确定两个积分常数", 2.0, depends_on=["q18.2", "q18.3"], carry_forward=True),
            _point(18, 5, "给出定义域 u>0 上完整函数 1/2(ln u)²+2lnu+1", 2.0, depends_on=["q18.4"], critical=True, carry_forward=True),
        ],
        answer_anchor_fields={
            "final_answer": {
                "kind": "expression",
                "expected": "log(u)**2/2+2*log(u)+1",
                "variables": ["u"],
                "weight": 1,
            }
        },
    ),
    _question(
        19,
        "solution",
        10,
        r"""
设函数 f(x) 在区间 (a,b) 内可导。证明：导函数 f'(x) 在 (a,b) 内严格单调增加的充分必要条件是，对 (a,b) 内任意 x1<x2<x3，均有
[f(x2)-f(x1)]/(x2-x1) < [f(x3)-f(x2)]/(x3-x2)。
""",
        "充分必要条件成立",
        [12, 13],
        answer_kind="literal",
        objective_weight=0,
        obligations=[
            "充分性方向从三点割线斜率严格递增推出任意两点处导数严格递增",
            "充分性极限论证正确处理单侧导数或等价的局部割线极限",
            "必要性方向在相邻区间应用拉格朗日中值定理",
            "由中值点次序与 f' 严格递增推出两段割线斜率严格不等式",
        ],
        scoring_points=[
            _point(19, 1, "充分性：为任意 s<t 选择逼近端点的三点并写出适用的割线斜率不等式", 2.0),
            _point(19, 2, "充分性：分别取单侧极限得到 f'(s)<f'(t)，极限方向与严格性论证成立", 3.0, depends_on=["q19.1"], critical=True),
            _point(19, 3, "必要性：在 (x1,x2)、(x2,x3) 分别应用拉格朗日中值定理并得到两个中值点", 2.0),
            _point(19, 4, "必要性：由 ξ1<ξ2 及 f' 严格递增推出两段割线斜率的严格不等式", 3.0, depends_on=["q19.3"], critical=True),
        ],
    ),
    _question(
        20,
        "solution",
        10,
        r"""
曲面 Σ 由直线 x=0,y=0 绕直线 x=t,y=t,z=t（t 为参数）旋转一周得到。Σ1 是 Σ 介于平面 x+y+z=0 与 x+y+z=1 之间部分的外侧。计算曲面侧积分
I=∬_(Σ1) x dy dz + (y+1) dz dx + (z+2) dx dy。
""",
        "-2*pi/sqrt(3)",
        [14, 15],
        accepted=["-2*sqrt(3)*pi/3"],
        obligations=[
            "识别旋转曲面为 xy+yz+zx=0 所描述的圆锥面",
            "用平面 x+y+z=1 补面构成封闭区域并明确外侧方向",
            "对闭合曲面正确应用高斯公式并计算体积分",
            "正确计算补面通量并作差得到 -2π/√3",
        ],
        scoring_points=[
            _point(20, 1, "由旋转轴与母线几何关系推出圆锥面 xy+yz+zx=0，而非仅猜测方程", 2.0),
            _point(20, 2, "确定截面圆、封闭体和侧面/补面的外法向关系", 2.0, depends_on=["q20.1"]),
            _point(20, 3, "对 F=(x,y+1,z+2) 正确计算散度，并在正确区域求闭曲面总通量", 2.0, depends_on=["q20.2"], carry_forward=True),
            _point(20, 4, "独立计算 x+y+z=1 圆盘补面的通量，面积、单位法向和符号正确", 2.0, depends_on=["q20.2"], carry_forward=True),
            _point(20, 5, "按外侧方向作差并得到侧面通量 -2π/√3", 2.0, depends_on=["q20.3", "q20.4"], critical=True, carry_forward=True),
        ],
        answer_anchor_fields={
            "final_answer": {
                "kind": "expression",
                "expected": "-2*pi/sqrt(3)",
                "accepted": ["-2*sqrt(3)*pi/3"],
                "variables": [],
                "weight": 1,
            }
        },
        rubric_version=Q20_RUBRIC_VERSION,
        rubric_source=Q20_RUBRIC_SOURCE,
        source_tier="expert_reconstructed",
    ),
    _question(
        21,
        "solution",
        15,
        r"""
设矩阵 A=[[0,-1,2],[-1,0,2],[-1,-1,a]]，已知 1 是 A 的特征多项式的重根。
(1) 求 a 的值；
(2) 求所有满足 Aα=α+β、A^2α=α+2β 的非零列向量 α、β。
""",
        "a=3；α=(a1,a2,a3)^T 为任意非零向量且 a1+a2≠2a3；β=(2a3-a1-a2)(1,1,1)^T",
        [15],
        answer_kind="literal",
        objective_weight=0,
        obligations=[
            "由 λ=1 为特征多项式重根得到 a=3",
            "由两式推出 (A-I)^2α=0 且 β=(A-I)α",
            "在 a=3 时正确刻画 ker((A-I)^2) 并排除 α=0",
            "保证 β 非零，即 a1+a2≠2a3，并给出 β 的完整参数表达",
        ],
        scoring_points=[
            _point(21, 1, "实际计算特征多项式，并用 λ=1 为重根的条件得到 a=3", 4.0, critical=True),
            _point(21, 2, "由两式消元得到 (A-I)²α=0 且 β=(A-I)α", 3.0),
            _point(21, 3, "在 a=3 时计算 ker((A-I)²)，证明 α 可取任意非零三维列向量", 3.0, depends_on=["q21.1", "q21.2"]),
            _point(21, 4, "明确 α=(a1,a2,a3)^T 非零这一参数限制", 2.0, depends_on=["q21.3"]),
            _point(21, 5, "给出 β=(2a3-a1-a2)(1,1,1)^T 并由 β≠0 得 a1+a2≠2a3", 3.0, depends_on=["q21.3"], critical=True),
        ],
        answer_anchor_fields={
            "a": {"kind": "expression", "expected": "3", "variables": [], "weight": 4},
            "beta_coefficient": {
                "kind": "expression",
                "expected": "2*a3-a1-a2",
                "accepted": ["-(a1+a2-2*a3)"],
                "variables": ["a1", "a2", "a3"],
                "weight": 3,
            },
            "nonzero_constraint": {
                "kind": "expression",
                "expected": "a1+a2-2*a3",
                "variables": ["a1", "a2", "a3"],
                "equivalent_up_to_nonzero_scalar": True,
                "weight": 3,
            },
        },
        answer_anchor_failure_cap=70,
    ),
    _question(
        22,
        "solution",
        15,
        r"""
投保人的损失事件发生时，保险公司的赔付额 Y 与投保人的损失额 X 的关系为：
Y=0（X≤100），Y=X-100（X>100）。
设损失事件发生时 X 的概率密度为 f(x)=2·100^2/(100+x)^3（x>0），x≤0 时为 0。
(1) 求 P{Y>0} 及 EY。
(2) 这种损失事件一年内发生的次数 N 服从参数为 8 的泊松分布。在 N=n（n≥1）的条件下，保险公司在一年内就这种损失事件产生的理赔次数 M 服从二项分布 B(n,p)，其中 p=P{Y>0}。求 M 的概率分布。
""",
        "P(Y>0)=1/4；E(Y)=50；M~Poisson(2)",
        [15, 16],
        answer_kind="literal",
        objective_weight=0,
        obligations=[
            "正确积分得到 P(Y>0)=P(X>100)=1/4",
            "按 Y=(X-100)1_{X>100} 计算并得到 EY=50",
            "识别泊松稀疏化或等价地对条件二项分布求和",
            "得到 M~Poisson(2)，即 P(M=m)=2^m e^(-2)/m!，m=0,1,2,...",
        ],
        scoring_points=[
            _point(22, 1, "写出并正确计算尾概率积分 P(X>100)=1/4", 3.5),
            _point(22, 2, "按 E[(X-100)1_{X>100}] 建立收敛积分并算得 50", 4.0),
            _point(22, 3, "由条件二项分布与 Poisson(8) 推导稀疏化结果，或完成等价求和", 3.5),
            _point(22, 4, "写出完整分布 P(M=m)=e^-2·2^m/m!（m=0,1,…），即 Poisson(2)", 4.0, depends_on=["q22.3"], critical=True),
        ],
        answer_anchor_fields={
            "probability": {"kind": "expression", "expected": "1/4", "variables": [], "weight": 3.5},
            "expected_value": {"kind": "expression", "expected": "50", "variables": [], "weight": 4},
            "poisson_lambda": {"kind": "expression", "expected": "2", "variables": [], "weight": 4},
        },
        answer_anchor_failure_cap=70,
    ),
]


def builtin_math_manifest() -> dict[str, Any]:
    return {
        "id": "builtin-2025-math1",
        "status": "published",
        "exam": MATH_EXAM_ID,
        "year": 2025,
        "title": "2025 年全国硕士研究生招生考试数学（一）",
        "source": {
            "filename": SOURCE_FILENAME,
            "sha256": SOURCE_SHA256,
            "size_bytes": 1_027_629,
            "page_count": SOURCE_PAGE_COUNT,
        },
        "score_structure": {
            "total": 150,
            "choice": {"questions": [1, 10], "points": 50},
            "fill": {"questions": [11, 16], "points": 30},
            "solution": {"questions": [17, 22], "points": 70},
        },
        "questions": BUILTIN_2025_MATH1_QUESTIONS,
    }


def build_builtin_math_cases() -> dict[str, list[dict[str, Any]]]:
    return build_published_math_cases(builtin_math_manifest())
