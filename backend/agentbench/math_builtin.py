from __future__ import annotations

from typing import Any

from .math_exam import MATH_EXAM_ID, build_published_math_cases

SOURCE_FILENAME = "ab27a44c5f0cbe5e.pdf"
SOURCE_SHA256 = "9ebd0eebbbfeef553880cb13af3528bbbb25630b86d7ed22fb5f9c85b0c659bf"
SOURCE_PAGE_COUNT = 17


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
    answer_kind: str = "expression",
    objective_weight: int = 40,
) -> dict[str, Any]:
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
        "solution_obligations": obligations or [],
        "answer_kind": answer_kind,
        "objective_weight": objective_weight,
        "review_status": "confirmed",
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
    ),
    _question(
        18,
        "solution",
        12,
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
    ),
    _question(
        19,
        "solution",
        12,
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
    ),
    _question(
        20,
        "solution",
        12,
        r"""
曲面 Σ 由直线 x=0,y=0 绕直线 x=t,y=t,z=t（t 为参数）旋转一周得到。Σ1 是 Σ 介于平面 x+y+z=0 与 x+y+z=1 之间部分的外侧。计算曲面侧积分
I=∬_(Σ1) x dy dz + (y+1) dz dx + (z+2) dx dy。
""",
        "sqrt(2)*pi/4-1",
        [14, 15],
        obligations=[
            "识别旋转曲面为 (x-t)^2+(y-t)^2+(z-t)^2=3t^2 所描述的圆锥面",
            "用平面 x+y+z=1 补面构成封闭区域并明确外侧方向",
            "对闭合曲面正确应用高斯公式并计算体积分",
            "正确计算补面通量并作差得到 √2π/4-1",
        ],
    ),
    _question(
        21,
        "solution",
        12,
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
    ),
    _question(
        22,
        "solution",
        12,
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
