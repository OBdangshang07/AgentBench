from __future__ import annotations

import hashlib
import json
import random
import textwrap
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from .db import Database, utc_now
from .math_builtin import build_builtin_math_cases
from .ncre_assets import blobs, blobs_paper02, blobs_paper03, exam_data_paper02, exam_data_paper03
from .ncre_assets.exam_data import (
    CHOICE_QUESTIONS,
    EXAM_NAME,
    PPT_FLOW_STEPS,
    PPT_SLIDE_TITLES,
    SOURCE_SUMMARY,
)

NAMESPACE = uuid.UUID("3a2259d0-189b-45fa-9caf-b729abdf2df1")


def stable_id(kind: str, name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{name}"))


MOCK_MODEL_ID = stable_id("model", "mock")
UNIFIED_RUNNER_ID = stable_id("runner", "unified")
CODEX_RUNNER_ID = stable_id("runner", "codex-cli")
CLAUDE_RUNNER_ID = stable_id("runner", "claude-code-cli")
CUSTOM_RUNNER_ID = stable_id("runner", "custom-command")
OPENCODE_RUNNER_ID = stable_id("runner", "opencode-cli")
REASONIX_RUNNER_ID = stable_id("runner", "reasonix-cli")
GEMINI_RUNNER_ID = stable_id("runner", "gemini-cli")
AIDER_RUNNER_ID = stable_id("runner", "aider-cli")
KIMI_RUNNER_ID = stable_id("runner", "kimi-code-cli")
QODER_RUNNER_ID = stable_id("runner", "qoder-cli")
FULL_SUITE_ID = stable_id("suite", "v1-full")
SMOKE_SUITE_ID = stable_id("suite", "v1-smoke")
V2_FULL_SUITE_ID = stable_id("suite", "v2-full")
V2_QUICK_SUITE_ID = stable_id("suite", "v2-quick")
PRACTICAL_SUITE_ID = stable_id("suite", "v2-practical")
FRONTIER_SUITE_ID = stable_id("suite", "v2-frontier")
ULTRA_SUITE_ID = stable_id("suite", "v3-ultra-prototype")
REASONING_SUITE_ID = stable_id("suite", "v2-reasoning-focus")
PLANNING_SUITE_ID = stable_id("suite", "v2-planning-focus")
CODING_SUITE_ID = stable_id("suite", "v2-coding-focus")
NCRE_OFFICE_SUITE_ID = stable_id("suite", "ncre-office-paper-01")
NCRE_OFFICE_PAPER02_SUITE_ID = stable_id("suite", "ncre-office-paper-02")
NCRE_OFFICE_PAPER03_SUITE_ID = stable_id("suite", "ncre-office-paper-03")
GAUNTLET_SUITE_ID = stable_id("suite", "v2-gauntlet")
GAUNTLET_LITE_SUITE_ID = stable_id("suite", "v2-gauntlet-lite")
MATH_2025_CLOSED_SUITE_ID = stable_id("suite", "postgraduate-math-2025-math1-closed")
MATH_2025_TOOL_SUITE_ID = stable_id("suite", "postgraduate-math-2025-math1-tools")

_NCRE_ASSET_DIR = Path(__file__).resolve().parent / "ncre_assets"


def _validator(kind: str, weight: float, **config: Any) -> dict[str, Any]:
    return {"type": kind, "weight": weight, "config": config}


def _ncre_judge(name: str) -> str:
    return (_NCRE_ASSET_DIR / name).read_text(encoding="utf-8")


def _ncre_metrics(pairs: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
    return [{"key": key, "name": name, "weight": weight} for key, name, weight in pairs]


def _ncre_metadata(
    section: str,
    exam_points: int,
    estimated_minutes: int,
    exam_paper: str,
    source_summary: str,
) -> dict[str, Any]:
    return {
        "difficulty": 4,
        "estimated_minutes": estimated_minutes,
        "capability": "office-application",
        "exam": "ncre-office",
        "exam_paper": exam_paper,
        "exam_section": section,
        "exam_points": exam_points,
        "source": source_summary,
        "internal_research_only": True,
    }


def _ncre_choice_instruction(exam_name: str, questions: list[tuple[str, str, dict[str, str]]]) -> str:
    lines = [
        f"{exam_name}选择题部分，共 20 题。请逐题作答，并将全部答案写入工作区根目录的 answers.json 文件。",
        "answers.json 格式为 JSON 对象，键为题目编号 q01~q20，值为选项字母（A/B/C/D），"
        '例如 {"q01": "A", "q02": "B", ...}。',
        "",
    ]
    for qid, stem, options in questions:
        lines.append(f"{qid}. {stem}")
        for letter in sorted(options):
            lines.append(f"{letter}. {options[letter]}")
        lines.append("")
    return "\n".join(lines)


_NCRE_PAPER01_WORD_METRICS = _ncre_metrics([
    ("w1", "页面尺寸", 3),
    ("w2", "页边距", 3),
    ("w3", "页面背景色", 3),
    ("w4", "全文微软雅黑", 3),
    ("w5", "标题字号与颜色", 4),
    ("w6", "对齐方式", 3),
    ("w7", "首行缩进", 3),
    ("w8", "段间距", 3),
    ("w9", "合并文档等价产物", 5),
])

_NCRE_PAPER01_EXCEL_METRICS = _ncre_metrics([
    ("e1", "套用表格样式", 3),
    ("e2", "货币专用格式", 3),
    ("e3", "图书名称 VLOOKUP", 5),
    ("e4", "单价 VLOOKUP", 5),
    ("e5", "小计公式", 4),
    ("e6", "B3 总销售额", 3),
    ("e7", "B4 MS Office 2012 销售额", 3),
    ("e8", "B5 隆华书店 2011Q3 销售额", 2),
    ("e9", "B6 月均销售额与格式", 2),
])

_NCRE_PAPER01_PPT_METRICS = _ncre_metrics([
    ("p1", "7 张幻灯片", 1),
    ("p2", "标题映射", 4),
    ("p3", "大纲层级文本", 4),
    ("p4", "首页版式", 2),
    ("p5", "应用主题", 2),
    ("p6", "销量统计表格", 4),
    ("p7", "SmartArt 流程图", 2),
    ("p8", "自定义放映", 1),
])

_NCRE_WORD_INSTRUCTION = (
    f"{EXAM_NAME}Word 操作题（30 分）。工作区已提供邀请函文稿草稿 Word.docx 与 通讯录.csv（姓名,称谓，共 5 人）。"
    "请完成以下操作：\n"
    "1. 打开 Word.docx，将页面设为自定义纸张：宽 30 厘米、高 18 厘米；页边距上、下各 2 厘米，左、右各 3 厘米。\n"
    "2. 为文档添加页面背景：原卷要求插入背景图片，因原素材图片缺失，降级要求为纯色填充，颜色值 #FDE9D9。\n"
    "3. 全文字体设置为微软雅黑；第 1 段“大学生网络创业交流会”与第 2 段“邀请函”字号设为“一号”，"
    "并将第 1 段文字设为蓝色。\n"
    "4. 对齐方式：第 1、2 段（标题）居中；“校学生会外联部”与日期两段落右对齐。\n"
    "5. 正文段落（正文第 4、5 段）设置首行缩进 2 字符；第 1、2 段设置段前、段后间距各 0.5 行。\n"
    "6. 邮件合并（等价口径）：用 Python（如 python-docx）基于 Word.docx 与 通讯录.csv 生成合并文档 Word-邀请函.docx："
    "通讯录中每位收件人各占一页（以分页符分隔），将正文中的“尊敬的(老师)：”替换为“尊敬的{姓名}：”。\n"
    "最终工作区须存在 Word.docx（已完成格式设置）与 Word-邀请函.docx 两个文件。"
)

_NCRE_EXCEL_INSTRUCTION = (
    f"{EXAM_NAME}Excel 操作题（30 分）。工作区已提供 Excel.xlsx，含三个工作表：订单明细表（第 2 行表头，"
    "第 3 行起 23 行数据，图书名称、单价、小计列暂为空）、编号对照表（图书编号、图书名称、单价）、"
    "统计报告（A 列统计项目、B 列待填）。请完成：\n"
    "1. 将订单明细表的数据区域套用内置表格样式（创建为“表”对象，含标题行，覆盖全部数据行）。\n"
    "2. 将单价列与小计列设置为货币专用格式（含 ￥ 符号、千位分隔符、两位小数）。\n"
    "3. 在订单明细表“图书名称”列用 VLOOKUP 公式，根据图书编号从编号对照表第 2 列自动填入图书名称（精确匹配）。\n"
    "4. 在“单价”列用 VLOOKUP 公式，根据图书编号从编号对照表第 3 列自动填入单价（精确匹配）。\n"
    "5. 在“小计”列用公式计算每笔订单的销售额（单价 × 销量）。\n"
    "6. 在统计报告 B3 计算所有订单的总销售金额；B4 计算《MS Office高级应用》图书 2012 年的总销售额；"
    "B5 计算隆华书店 2011 年第 3 季度（7 月 1 日至 9 月 30 日）的总销售额；"
    "B6 计算隆华书店 2011 年的每月平均销售额（保留 2 位小数，单元格显示两位小数格式）。\n"
    "评分以单元格计算值为准，公式写法不限。完成后保存 Excel.xlsx。"
)

_NCRE_PPT_INSTRUCTION = (
    f"{EXAM_NAME}PowerPoint 操作题（20 分）。工作区已提供素材文档 图书策划案.docx（含多级标题结构）。"
    "请将其改造为演示文稿并保存为 PowerPoint.pptx，要求：\n"
    "1. 共 7 张幻灯片，严格按素材顺序，标题依次为：" + "、".join(PPT_SLIDE_TITLES)
    + "。素材中 Heading 1 作为每页幻灯片标题；Heading 2 作为该页一级文本内容；Heading 3 作为该页二级文本内容。\n"
    "2. 第 1 页幻灯片版式设为“标题幻灯片”（Title Slide）。\n"
    "3. 为演示文稿应用任意一个非默认的内置主题。\n"
    "4. 第 6 页插入一个 6 行 5 列的表格，首行标题依次为：图书名称、出版社、作者、定价、销量（其余单元格内容自拟）。\n"
    "5. 第 7 页插入 SmartArt 流程图，按顺序包含 7 个步骤：" + "、".join(PPT_FLOW_STEPS) + "。\n"
    "6. 创建两个自定义放映方案：“放映方案1”放映第 1、2、4、7 页；“放映方案2”放映第 1、2、3、5、6 页。\n"
    "完成后保存 PowerPoint.pptx。"
)

_NCRE_PAPER02_WORD_METRICS = _ncre_metrics([
    ("w1", "第1页自定义纸张", 4),
    ("w2", "第1页页边距", 3),
    ("w3", "页面背景填充", 2),
    ("w4", "主标题字体格式", 4),
    ("w5", "第2页A4横向", 3),
    ("w6", "报告人姓名输入", 2),
    ("w7", "日程安排表", 5),
    ("w8", "报名流程列表", 3),
    ("w9", "报告人介绍排版", 4),
])

_NCRE_PAPER02_EXCEL_METRICS = _ncre_metrics([
    ("e1", "文件与结构", 3),
    ("e2", "数字格式", 3),
    ("e3", "条件格式", 3),
    ("e4", "总分与平均分", 5),
    ("e5", "班级提取", 4),
    ("e6", "分类汇总工作表", 5),
    ("e7", "柱状分析图工作表", 4),
    ("e8", "簇状柱形图", 3),
])

_NCRE_PAPER02_PPT_METRICS = _ncre_metrics([
    ("p1", "文件与幻灯片数量", 2),
    ("p2", "应用主题", 3),
    ("p3", "标题页要素", 3),
    ("p4", "内容板块与版式", 4),
    ("p5", "图片数量", 2),
    ("p6", "超链接数量", 4),
    ("p7", "文件名", 2),
])

_NCRE_PAPER03_WORD_METRICS = _ncre_metrics([
    ("w1", "删除西文空格", 3),
    ("w2", "16开纸张与页边距", 2),
    ("w3", "封面独占一页", 3),
    ("w4", "咨询情况表与饼图", 5),
    ("w5", "标题样式层级", 5),
    ("w6", "超链接与脚注", 4),
    ("w7", "正文两栏", 3),
    ("w8", "目录域", 3),
    ("w9", "页眉与页码", 2),
])

_NCRE_PAPER03_EXCEL_METRICS = _ncre_metrics([
    ("e1", "两表导入与表格样式", 4),
    ("e2", "千分位格式", 3),
    ("e3", "比较数据合并排序", 3),
    ("e4", "人口增长数列", 4),
    ("e5", "比重变化列", 4),
    ("e6", "统计指标表", 4),
    ("e7", "超5000万地区降序榜", 4),
    ("e8", "汇总分析透视降级", 4),
])

_NCRE_PAPER03_PPT_METRICS = _ncre_metrics([
    ("p1", "课件合并与双主题", 3),
    ("p2", "物质的状态新页", 3),
    ("p3", "蒸发沸腾异同表格页", 3),
    ("p4", "内部超链接", 4),
    ("p5", "编号与页脚", 3),
    ("p6", "幻灯片切换", 2),
    ("p7", "文件名", 2),
])

_NCRE_PAPER02_WORD_INSTRUCTION = (
    f"{exam_data_paper02.EXAM_NAME}Word 操作题（30 分）。工作区已提供海报文稿素材 WORD.docx"
    "（第1页竖版海报文字，第2页活动细则与日程安排）。请完成以下操作：\n"
    "1. 第1页设置自定义纸张：宽 27 厘米、高 35 厘米；页边距上、下各 5 厘米，左、右各 3 厘米。"
    "在“主办：校学工处”段后插入分页符使第2页单独成页，第2页纸张设为 A4 横向、普通页边距。\n"
    "2. 为文档设置页面背景纯色填充，颜色值 #FFF2CC（原卷要求插入背景图片，因素材缺失降级为纯色填充）。\n"
    "3. 文字格式：主标题“领慧讲堂”为微软雅黑、62 磅、红色；“就业讲座”为黑体、小初（36 磅）、深蓝色；"
    "报告题目、报告人等明细行为华文行楷、二号（22 磅）、白色；第2页标题为黑体、二号、居中。\n"
    "4. 主标题与第2页标题居中对齐；第1页各明细段落设置段前、段后间距各 0.5 行。\n"
    "5. 在第1页“报告人：”后输入 赵蕈。\n"
    "6. 在第2页插入 4 行 3 列日程安排表：首行标题为 时间、主题、报告人；数据行依次为 "
    "18:30-19:00 签到（报告人为空）、19:00-19:20 大学生职场定位和职业准备 王老师、"
    "19:20-21:10 大学生人生规划 特约专家、21:10-21:30 现场提问 王老师。\n"
    "7. 将报名流程以编号列表呈现：学工处报名、确认坐席、领取资料、领取门票（原卷 SmartArt 流程图降级为编号列表）。\n"
    "8. 报告人介绍段设置两端对齐与首行缩进 2 字符（原卷首字下沉降级为普通段落）。\n"
    "完成后保存 WORD.docx。"
)

_NCRE_PAPER02_EXCEL_INSTRUCTION = (
    f"{exam_data_paper02.EXAM_NAME}Excel 操作题（30 分）。工作区已提供 Excel.xlsx"
    "（单个工作表“成绩表”：A 列学号、B 列姓名、C 列班级待填、D~J 列为语文、数学、英语、物理、化学、生物、政治 "
    "7 科成绩，第 1 行表头，第 2~13 行共 12 名学生数据）与参考数据 成绩单.csv。请完成：\n"
    "1. 将学号列设为文本格式；7 科成绩列与平均分列数字格式设为保留两位小数（0.00）。\n"
    "2. 条件格式：语文、数学、英语三列，单元格值大于等于 110 时填充浅红色（如 FFC7CE）；"
    "物理、化学、生物、政治四列，单元格值大于 95 时字体设为蓝色（如 0000FF）。\n"
    "3. K 列用 SUM 公式计算每位学生 7 科总分（K2:K13）；L 列用 AVERAGE 公式计算平均分（L2:L13，两位小数格式）。\n"
    "4. C 列班级用文本函数从学号第 3、4 位提取并拼接“班”字（如 =TEXT(MID(A2,3,2),\"0\")&\"班\"），结果为 1班/2班/3班。\n"
    "5. 复制“成绩表”为新工作表并重命名为含“分类汇总”的名称（如“成绩单分类汇总”），将该表标签颜色设为蓝色（如 0070C0），"
    "并按班级分类汇总计算每班每科平均分（每班一个分组）。\n"
    "6. 新建工作表“柱状分析图”，插入簇状柱形图：分类（X轴）为 7 个科目，数据系列为 3 个班级的各科平均分（取自分类汇总结果）。\n"
    "评分以单元格计算值与工作簿结构为准。完成后保存 Excel.xlsx。"
)

_NCRE_PAPER02_PPT_INSTRUCTION = (
    f"{exam_data_paper02.EXAM_NAME}PowerPoint 操作题（20 分）。工作区已提供素材文档 水资源素材大纲.docx"
    "（含“水的知识、水的应用、节水工作”三大板块多级大纲）。请新建演示文稿并保存为 水资源利用与节水.pptx，要求：\n"
    "1. 应用一个非默认主题。\n"
    "2. 第1张为“标题幻灯片”版式：主标题 水资源利用与节水，副标题或正文含制作单位 北京节水展馆 与制作日期（如 2013年5月18日）。\n"
    "3. 共不少于 5 张幻灯片（建议 6 张），按素材大纲顺序覆盖三大板块：水的知识、水的应用、节水工作，内容取材于素材大纲。\n"
    "4. 全套幻灯片至少使用 3 种不同版式（如标题幻灯片、标题和内容、两栏内容、仅标题）。\n"
    "5. 至少插入 2 张图片（占位图即可）与 2 个超链接（可链接本文档其它幻灯片或外部网址）。\n"
    "完成后保存 水资源利用与节水.pptx。"
)

_NCRE_PAPER03_WORD_INSTRUCTION = (
    f"{exam_data_paper03.EXAM_NAME}Word 操作题（30 分）。工作区已提供素材 年报.docx"
    "（《2012年北京市政府信息公开工作年度报告》长文档）与 咨询情况表.csv。请完成以下操作：\n"
    "1. 删除文档中汉字与西文、数字之间的半角空格（如“1085 条”改为“1085条”）。\n"
    "2. 页面设置为 16 开纸张：宽 18.4 厘米、高 26 厘米；页边距上 3.2 厘米、下 3 厘米、左右各 2.5 厘米。\n"
    "3. 封面（报告标题、“北京市统计局　国家统计局北京调查总队”、“二〇一三年三月”三段）独占一页且标题居中。\n"
    "4. 将咨询情况的蓝色文字段转换为 4 行 3 列表格：表头 咨询方式/人次/所占比例(%)，数据行 现场咨询 93 5.04、"
    "电话咨询 1515 82.07、网上咨询 238 12.89、合计 1846 100（与 咨询情况表.csv 一致）；套用内置表格样式，"
    "并在表格后插入饼图（分类为咨询方式、数值为人次数、数据标签仅显示百分比）。\n"
    "5. 将“一、二、……”开头的段落设为标题 1 样式，“（一）（二）……”开头的段落设为标题 2 样式，"
    "“1、2、……”开头的段落设为标题 3 样式。\n"
    "6. 将引言中红色文字“统计局队政府网站”设为超链接，指向 http://www.bjstats.gov.cn/，"
    "并在该处添加脚注（注释文字：北京市统计局、国家统计局北京调查总队官方网站）。\n"
    "7. 除封面与目录页外，正文设置为两栏。\n"
    "8. 在封面与正文之间插入目录域（含 1-3 级标题）。\n"
    "9. 正文部分设置奇偶页不同页眉：奇数页页码靠右、偶数页页码靠左，页眉含页码域。\n"
    "完成后保存 年报.docx。"
)

_NCRE_PAPER03_EXCEL_INSTRUCTION = (
    f"{exam_data_paper03.EXAM_NAME}Excel 操作题（30 分）。工作区已提供素材 第五次普查数据.csv 与 第六次普查数据.csv"
    "（各 31 个地区，列：地区/人口数(人)/比重(%)）。请新建工作簿保存为 Excel.xlsx，完成：\n"
    "1. 创建“第五次普查数据”与“第六次普查数据”两个工作表，分别从两份 CSV 导入数据（首行为表头，自 A1 开始，"
    "不改变原行序），并为两表数据区域套用内置表格样式（创建含标题行的表格对象，样式使偶数行带底纹）。\n"
    "2. 两表人口数列数字格式设为千分位整数（#,##0）。\n"
    "3. 新建工作表“比较数据”合并两次普查数据：A1 为列标题 地区，31 个地区按地区名升序排列，"
    "其后依次为 2000年人口数、2000年比重(%)、2010年人口数、2010年比重(%)。\n"
    "4. 在“比较数据”表新增两列：人口增长数（=2010年人口数−2000年人口数）、"
    "比重变化（=2010年比重−2000年比重，百分点，保留两位小数）。\n"
    "5. 新建工作表“统计指标”，包含五项统计：地区数、2000年全国合计人口数、2010年全国合计人口数、"
    "2010年人口超过 5000 万的地区数、上述地区 2010 年人口平均数（建议用 COUNT/AVERAGEIF 等公式实现）。\n"
    "6. 新建工作表“透视分析”：提取 2010 年人口数大于 5000 万的地区，按 2010 年人口数降序排列，"
    "列出 地区、2010年人口数、2010年比重(%)、人口增长数（原卷数据透视表降级为扁平汇总）。\n"
    "评分以单元格计算值为准，全国合计口径为 31 地区人口求和。完成后保存 Excel.xlsx。"
)

_NCRE_PAPER03_PPT_INSTRUCTION = (
    f"{exam_data_paper03.EXAM_NAME}PowerPoint 操作题（20 分）。工作区已提供两个课件片段 第1-2节.pptx 与 第3-5节.pptx"
    "（北师大版八年级上册 第一章 物态及其变化，两份课件主题不同）。请整合为一份完整课件并保存为 物理课件.pptx，要求：\n"
    "1. 将两个课件的全部 6 页按顺序合并（第1-3页来自第1-2节，第4-6页来自第3-5节），"
    "保留各页版式与主题归属（整合后需引用 2 个不同的幻灯片母版/主题）。\n"
    "2. 在第 3 张之后插入一张“仅标题”版式幻灯片，标题为 物质的状态（插入后为第 4 张）。\n"
    "3. 在第 6 张之后插入一张“标题和内容”版式幻灯片，标题为 蒸发和沸腾的异同点（插入后为第 7 张），"
    "内容区放置 4 行 3 列对比表：表头 项目/蒸发/沸腾；数据行 发生部位（液体表面/液体内部和表面同时）、"
    "温度条件（任何温度/达到沸点）、剧烈程度（缓慢/剧烈）。\n"
    "4. 在第 4 张添加文字“返回第2节熔化和凝固”并设置超链接到第 3 张幻灯片；"
    "在第 7 张添加文字“返回第4节升华和凝华”并设置超链接到第 6 张幻灯片。\n"
    "5. 除第 1 张外为其余幻灯片添加幻灯片编号，并为所有幻灯片设置页脚文字 第一章 物态及其变化。\n"
    "6. 为所有幻灯片设置同一种切换方式。\n"
    "7. 最终共 9 张幻灯片（第 9 张可为 谢谢观看 结束页）。\n"
    "完成后保存 物理课件.pptx。"
)

_NCRE_OPERATION_LIMITS = {
    "max_steps": 40,
    "timeout_seconds": 2700,
    "validator_timeout_seconds": 300,
    "token_budget": 60000,
    "network": "disabled",
    "docker_image": "agentbench/office-validator:1.0",
}


_NCRE_SECTION_PLAN = {
    "choice": (20, 15),
    "word": (30, 35),
    "excel": (30, 35),
    "ppt": (20, 30),
}

_NCRE_PAPER_SPECS: list[dict[str, Any]] = [
    {
        "paper_no": "01",
        "exam_paper": "2016-03-paper-01",
        "exam_name": EXAM_NAME,
        "source_summary": SOURCE_SUMMARY,
        "choice_questions": CHOICE_QUESTIONS,
        "instructions": {
            "word": _NCRE_WORD_INSTRUCTION,
            "excel": _NCRE_EXCEL_INSTRUCTION,
            "ppt": _NCRE_PPT_INSTRUCTION,
        },
        "metrics": {
            "word": _NCRE_PAPER01_WORD_METRICS,
            "excel": _NCRE_PAPER01_EXCEL_METRICS,
            "ppt": _NCRE_PAPER01_PPT_METRICS,
        },
        "judges": {
            "choice": "judge_choice.py",
            "word": "judge_word.py",
            "excel": "judge_excel.py",
            "ppt": "judge_ppt.py",
        },
        "initial_files": {
            "word": {
                "Word.docx": "base64:" + blobs.WORD_DOCX_B64,
                "通讯录.csv": blobs.CONTACTS_CSV,
            },
            "excel": {"Excel.xlsx": "base64:" + blobs.EXCEL_XLSX_B64},
            "ppt": {"图书策划案.docx": "base64:" + blobs.PPT_SOURCE_DOCX_B64},
        },
        "file_checks": {
            "choice": [("answers.json", 5)],
            "word": [("Word-邀请函.docx", 3), ("Word.docx", 2)],
            "excel": [("Excel.xlsx", 5)],
            "ppt": [("PowerPoint.pptx", 5)],
        },
        "titles": {
            "choice": (
                "NCRE二级MS Office真题卷1 · 选择题（20题）",
                "NCRE 二级 MS Office 高级应用 2016年3月真题第1套选择题部分，答案写入 answers.json。",
            ),
            "word": (
                "NCRE二级MS Office真题卷1 · Word 邀请函排版与合并",
                "对邀请函草稿完成页面、字体、段落格式设置，并生成等价邮件合并文档 Word-邀请函.docx。",
            ),
            "excel": (
                "NCRE二级MS Office真题卷1 · Excel 图书销售统计",
                "对订单明细套用表格与货币格式、VLOOKUP 填充与小计公式，并在统计报告计算四项统计值。",
            ),
            "ppt": (
                "NCRE二级MS Office真题卷1 · PowerPoint 图书策划案改造",
                "将多级标题素材文档改造为 7 页演示文稿：版式、主题、表格、SmartArt 与自定义放映。",
            ),
        },
    },
    {
        "paper_no": "02",
        "exam_paper": "classic-set2-paper-02",
        "exam_name": exam_data_paper02.EXAM_NAME,
        "source_summary": exam_data_paper02.SOURCE_SUMMARY,
        "choice_questions": exam_data_paper02.CHOICE_QUESTIONS,
        "instructions": {
            "word": _NCRE_PAPER02_WORD_INSTRUCTION,
            "excel": _NCRE_PAPER02_EXCEL_INSTRUCTION,
            "ppt": _NCRE_PAPER02_PPT_INSTRUCTION,
        },
        "metrics": {
            "word": _NCRE_PAPER02_WORD_METRICS,
            "excel": _NCRE_PAPER02_EXCEL_METRICS,
            "ppt": _NCRE_PAPER02_PPT_METRICS,
        },
        "judges": {
            "choice": "judge_choice_paper02.py",
            "word": "judge_word_paper02.py",
            "excel": "judge_excel_paper02.py",
            "ppt": "judge_ppt_paper02.py",
        },
        "initial_files": {
            "word": {"WORD.docx": "base64:" + blobs_paper02.PAPER02_WORD_DOCX_B64},
            "excel": {
                "Excel.xlsx": "base64:" + blobs_paper02.PAPER02_EXCEL_XLSX_B64,
                "成绩单.csv": blobs_paper02.PAPER02_GRADES_CSV,
            },
            "ppt": {"水资源素材大纲.docx": "base64:" + blobs_paper02.PAPER02_PPT_SOURCE_DOCX_B64},
        },
        "file_checks": {
            "choice": [("answers.json", 5)],
            "word": [("WORD.docx", 5)],
            "excel": [("Excel.xlsx", 5)],
            "ppt": [("水资源利用与节水.pptx", 5)],
        },
        "titles": {
            "choice": (
                "NCRE二级MS Office真题卷2 · 选择题（20题）",
                "NCRE 二级 MS Office 高级应用经典题库第2套选择题部分，答案写入 answers.json。",
            ),
            "word": (
                "NCRE二级MS Office真题卷2 · Word 领慧讲堂海报制作",
                "对海报素材完成双页纸张、背景、文字格式设置，并插入日程表与报名流程列表。",
            ),
            "excel": (
                "NCRE二级MS Office真题卷2 · Excel 学生成绩单统计",
                "对成绩单完成格式与条件格式、总分平均分、班级提取、分类汇总与柱状图分析。",
            ),
            "ppt": (
                "NCRE二级MS Office真题卷2 · PowerPoint 水资源利用与节水",
                "根据素材大纲新建节水科普演示文稿：主题、标题页、多版式、图片与超链接。",
            ),
        },
    },
    {
        "paper_no": "03",
        "exam_paper": "classic-set4-paper-03",
        "exam_name": exam_data_paper03.EXAM_NAME,
        "source_summary": exam_data_paper03.SOURCE_SUMMARY,
        "choice_questions": exam_data_paper03.CHOICE_QUESTIONS,
        "instructions": {
            "word": _NCRE_PAPER03_WORD_INSTRUCTION,
            "excel": _NCRE_PAPER03_EXCEL_INSTRUCTION,
            "ppt": _NCRE_PAPER03_PPT_INSTRUCTION,
        },
        "metrics": {
            "word": _NCRE_PAPER03_WORD_METRICS,
            "excel": _NCRE_PAPER03_EXCEL_METRICS,
            "ppt": _NCRE_PAPER03_PPT_METRICS,
        },
        "judges": {
            "choice": "judge_choice_paper03.py",
            "word": "judge_word_paper03.py",
            "excel": "judge_excel_paper03.py",
            "ppt": "judge_ppt_paper03.py",
        },
        "initial_files": {
            "word": {
                "年报.docx": "base64:" + blobs_paper03.PAPER03_REPORT_DOCX_B64,
                "咨询情况表.csv": blobs_paper03.PAPER03_CONSULT_CSV,
            },
            "excel": {
                "第五次普查数据.csv": blobs_paper03.PAPER03_CENSUS_2000_CSV,
                "第六次普查数据.csv": blobs_paper03.PAPER03_CENSUS_2010_CSV,
            },
            "ppt": {
                "第1-2节.pptx": "base64:" + blobs_paper03.PAPER03_COURSEWARE_A_PPTX_B64,
                "第3-5节.pptx": "base64:" + blobs_paper03.PAPER03_COURSEWARE_B_PPTX_B64,
            },
        },
        "file_checks": {
            "choice": [("answers.json", 5)],
            "word": [("年报.docx", 5)],
            "excel": [("Excel.xlsx", 5)],
            "ppt": [("物理课件.pptx", 5)],
        },
        "titles": {
            "choice": (
                "NCRE二级MS Office真题卷3 · 选择题（20题）",
                "NCRE 二级 MS Office 高级应用经典题库第4套选择题部分，答案写入 answers.json。",
            ),
            "word": (
                "NCRE二级MS Office真题卷3 · Word 统计工作年报排版",
                "对年报长文档完成封面、标题样式、目录、表格与饼图、分栏与页眉页脚排版。",
            ),
            "excel": (
                "NCRE二级MS Office真题卷3 · Excel 人口普查数据整合",
                "导入两次普查分地区数据，完成表格化、合并比较、统计指标与降序榜分析。",
            ),
            "ppt": (
                "NCRE二级MS Office真题卷3 · PowerPoint 物理课件整合",
                "将两个不同主题的课件片段合并为 9 页课件：新增页、对比表、内部超链接与页脚。",
            ),
        },
    },
]


def _build_ncre_paper_cases(spec: dict[str, Any]) -> list[dict[str, Any]]:
    paper_no = spec["paper_no"]
    choice_judge = spec["judges"]["choice"]
    cases: list[dict[str, Any]] = []
    title, description = spec["titles"]["choice"]
    cases.append(
        {
            "slug": f"ncre.office.paper{paper_no}.choice",
            "version": "1.0.0",
            "category": "office-exam",
            "title": title,
            "description": description,
            "instruction": _ncre_choice_instruction(spec["exam_name"], spec["choice_questions"]),
            "tools": ["filesystem"],
            "limits": {
                "max_steps": 12,
                "timeout_seconds": 900,
                "token_budget": 16000,
                "docker_image": "agentbench/office-validator:1.0",
            },
            "validators": [
                _validator(
                    "command_metrics",
                    90,
                    command=f"python {{private_root}}/{choice_judge}",
                    metrics=_ncre_metrics(
                        [(f"q{i:02d}", f"选择题 {i:02d}", 1) for i in range(1, 21)]
                    ),
                    private_files={choice_judge: _ncre_judge(choice_judge)},
                ),
                _validator("file_exists", 5, path="answers.json"),
                _validator("forbidden_paths", 5, paths=["../**"]),
            ],
            "tags": ["ncre", "office-exam", "choice"],
            "initial_files": {},
            "metadata": _ncre_metadata(
                "choice", 20, 15, spec["exam_paper"], spec["source_summary"]
            ),
        }
    )
    for section, tag in (("word", "word"), ("excel", "excel"), ("ppt", "powerpoint")):
        judge = spec["judges"][section]
        validators: list[dict[str, Any]] = [
            _validator(
                "command_metrics",
                90,
                command=f"python {{private_root}}/{judge}",
                metrics=spec["metrics"][section],
                private_files={judge: _ncre_judge(judge)},
            ),
        ]
        validators.extend(
            _validator("file_exists", weight, path=path)
            for path, weight in spec["file_checks"][section]
        )
        validators.append(_validator("forbidden_paths", 5, paths=["../**"]))
        title, description = spec["titles"][section]
        exam_points, estimated_minutes = _NCRE_SECTION_PLAN[section]
        cases.append(
            {
                "slug": f"ncre.office.paper{paper_no}.{section}",
                "version": "1.0.0",
                "category": "office-exam",
                "title": title,
                "description": description,
                "instruction": spec["instructions"][section],
                "tools": ["filesystem", "shell"],
                "limits": dict(_NCRE_OPERATION_LIMITS),
                "validators": validators,
                "tags": ["ncre", "office-exam", tag],
                "initial_files": spec["initial_files"][section],
                "metadata": _ncre_metadata(
                    section, exam_points, estimated_minutes, spec["exam_paper"], spec["source_summary"]
                ),
            }
        )
    return cases


def _build_ncre_office_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for spec in _NCRE_PAPER_SPECS:
        cases.extend(_build_ncre_paper_cases(spec))
    return cases


def build_catalog() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(1, 26):
        expected = f"READY-{index:03d}"
        cases.append(
            {
                "slug": f"instruction.exact-{index:03d}",
                "version": "1.0.0",
                "category": "instruction-following",
                "title": f"精确格式指令 {index:02d}",
                "description": "测试无额外解释的严格输出能力。",
                "instruction": f"只输出字符串 {expected}，不要添加标点、代码块或解释。",
                "tools": [],
                "limits": {"max_steps": 4, "timeout_seconds": 90, "token_budget": 2000},
                "validators": [_validator("exact_match", 90, expected=expected)],
                "tags": ["format", "deterministic"],
                "initial_files": {},
                "metadata": {
                    "demo_response": expected,
                    "difficulty": 1,
                    "estimated_minutes": 1,
                    "capability": "format-control",
                },
            }
        )
    for index in range(1, 6):
        left = index * 7 + 3
        right = index + 11
        offset = (index % 5) * 3
        answer = str(left * right + offset)
        cases.append(
            {
                "slug": f"reasoning.arithmetic-{index:03d}",
                "version": "1.0.0",
                "category": "reasoning",
                "title": f"多步算术推理 {index:02d}",
                "description": "测试简单多步计算以及答案格式遵循。",
                "instruction": (
                    f"计算 ({left} × {right}) + {offset}。只输出十进制整数结果，不要展示推导过程。"
                ),
                "tools": [],
                "limits": {"max_steps": 4, "timeout_seconds": 90, "token_budget": 3000},
                "validators": [_validator("exact_match", 90, expected=answer)],
                "tags": ["math", "deterministic"],
                "initial_files": {},
                "metadata": {
                    "demo_response": answer,
                    "difficulty": 2,
                    "estimated_minutes": 2,
                    "capability": "reasoning",
                },
            }
        )
    cases.extend(_build_advanced_math_cases())

    for index in range(1, 26):
        target = f"deliverables/note-{index:03d}.txt"
        content = f"AGENTBENCH-FILE-{index:03d}\nvalidated=true\n"
        cases.append(
            {
                "slug": f"tools.file-{index:03d}",
                "version": "1.0.0",
                "category": "tool-use",
                "title": f"受限文件创建 {index:02d}",
                "description": "测试 Agent 是否会使用文件工具产生精确交付物。",
                "instruction": (
                    f"在工作区创建 `{target}`，文件内容必须严格为两行：\n"
                    f"AGENTBENCH-FILE-{index:03d}\nvalidated=true"
                ),
                "tools": ["filesystem"],
                "limits": {"max_steps": 8, "timeout_seconds": 120, "token_budget": 5000},
                "validators": [
                    _validator("file_exists", 35, path=target),
                    _validator("file_content", 55, path=target, expected=content),
                ],
                "tags": ["filesystem", "artifact"],
                "initial_files": {},
                "metadata": {
                    "demo_actions": [
                        {"tool": "write_file", "arguments": {"path": target, "content": content}}
                    ],
                    "demo_response": "文件已创建。",
                    "difficulty": 2,
                    "estimated_minutes": 3,
                    "capability": "file-operation",
                },
            }
        )

    for index in range(1, 26):
        factor = index % 7 + 2
        offset = index % 4
        buggy = "def transform(value):\n    return value\n"
        fixed = f"def transform(value):\n    return value * {factor} + {offset}\n"
        command = (
            'python -c "import solution; '
            f"assert solution.transform(3) == {3 * factor + offset}; "
            f'assert solution.transform(-2) == {-2 * factor + offset}"'
        )
        cases.append(
            {
                "slug": f"coding.fix-function-{index:03d}",
                "version": "1.0.0",
                "category": "software-engineering",
                "title": f"修复 Python 函数 {index:02d}",
                "description": "测试代码理解、文件修改和隐藏命令验证。",
                "instruction": (
                    "修复 `solution.py` 中的 `transform(value)`，使它返回 "
                    f"`value * {factor} + {offset}`。不要创建或修改 tests 目录。"
                ),
                "tools": ["filesystem", "search", "shell"],
                "limits": {
                    "max_steps": 20,
                    "timeout_seconds": 300,
                    "token_budget": 12000,
                    "network": "disabled",
                    "docker_image": "python:3.12-alpine",
                },
                "validators": [
                    _validator("command", 80, command=command),
                    _validator("forbidden_paths", 10, paths=["tests", ".git"]),
                ],
                "tags": ["python", "coding", "docker"],
                "initial_files": {"solution.py": buggy},
                "metadata": {
                    "demo_actions": [
                        {
                            "tool": "write_file",
                            "arguments": {"path": "solution.py", "content": fixed},
                        }
                    ],
                    "demo_response": "已修复 transform 并准备验证。",
                    "difficulty": 3,
                    "estimated_minutes": 6,
                    "capability": "coding",
                },
            }
        )
    cases.extend(_build_knowledge_work_cases())
    cases.extend(_build_data_analysis_cases())
    cases.extend(_build_agentic_workflow_cases())
    cases.extend(_build_advanced_coding_cases())
    cases.extend(_build_security_cases())
    cases.extend(_build_planning_cases())
    from .v3_catalog import upgrade_v3_cases

    cases = upgrade_v3_cases(cases)
    # NCRE 二级真题卷追加在末尾，避免影响上方基于索引的套件切片。
    cases.extend(_build_ncre_office_cases())
    return cases


def _build_advanced_math_cases() -> list[dict[str, Any]]:
    problems = [
        {
            "slug": "math.integral-beta-polynomial",
            "title": "Beta 型定积分",
            "description": "化简高次多项式定积分并给出最简有理数。",
            "instruction": "计算定积分 ∫[0,1] x^3(1-x)^4 dx。只输出最简分数。",
            "expected": "1/280",
            "topic": "integral",
            "difficulty": 4,
        },
        {
            "slug": "math.integral-bose-einstein",
            "title": "反常积分与特殊值",
            "description": "识别 Gamma 与 zeta 特殊值对应的反常积分。",
            "instruction": "计算 ∫[0,∞] x^3/(e^x-1) dx。用 pi 表示圆周率，只输出完全化简结果。",
            "expected": "pi^4/15",
            "topic": "integral",
            "difficulty": 5,
        },
        {
            "slug": "math.integral-log-sine",
            "title": "对数三角积分",
            "description": "求经典对数三角反常积分的精确值。",
            "instruction": "计算 ∫[0,pi/2] ln(sin(x)) dx。使用 pi 与 ln，只输出 `-(pi*ln(2))/2` 这种规范形式。",
            "expected": "-(pi*ln(2))/2",
            "topic": "integral",
            "difficulty": 5,
        },
        {
            "slug": "math.integral-parameter-differentiation",
            "title": "参数微分反常积分",
            "description": "通过参数微分或复积分计算振荡衰减积分。",
            "instruction": "计算 ∫[0,∞] x^2*e^(-2x)*sin(3x) dx。只输出最简分数。",
            "expected": "18/2197",
            "topic": "integral",
            "difficulty": 5,
        },
        {
            "slug": "math.derivative-high-order-product",
            "title": "高阶导数精确值",
            "description": "利用级数系数或 Leibniz 公式计算高阶导数。",
            "instruction": "令 f(x)=x^5*e^(2x)。计算 f 的第 8 阶导数在 x=0 的值，只输出整数。",
            "expected": "53760",
            "topic": "differential-calculus",
            "difficulty": 4,
        },
        {
            "slug": "math.derivative-implicit-third",
            "title": "隐函数三阶导数",
            "description": "对隐式代数曲线连续求导到三阶。",
            "instruction": "曲线 x^2+x*y+y^2=3 在 (1,1) 附近定义 y(x)。求 y'''(1)，只输出最简分数。",
            "expected": "-2/3",
            "topic": "differential-calculus",
            "difficulty": 5,
        },
        {
            "slug": "math.derivative-taylor-coefficient",
            "title": "复指数型 Taylor 系数",
            "description": "提取指数与三角函数乘积的高阶 Taylor 系数。",
            "instruction": "求 e^x*cos(x) 的 Maclaurin 展开中 x^8 的系数。只输出最简分数。",
            "expected": "1/2520",
            "topic": "differential-calculus",
            "difficulty": 5,
        },
        {
            "slug": "math.derivative-directional-second",
            "title": "多元函数二阶方向导数",
            "description": "由 Hessian 计算指定单位方向的二阶方向导数。",
            "instruction": "令 f(x,y)=e^(x*y)，单位向量 v=(3/5,4/5)。求 f 在 (0,1) 沿 v 的二阶方向导数，只输出最简分数。",
            "expected": "33/25",
            "topic": "differential-calculus",
            "difficulty": 5,
        },
        {
            "slug": "math.ode-second-order-ivp",
            "title": "二阶常系数初值问题",
            "description": "求解二阶线性微分方程并在特殊点精确求值。",
            "instruction": "解 y''-3y'+2y=0，且 y(0)=0、y'(0)=1。求 y(ln(2))，只输出结果。",
            "expected": "2",
            "topic": "differential-equation",
            "difficulty": 4,
        },
        {
            "slug": "math.ode-euler-cauchy",
            "title": "重根 Euler 微分方程",
            "description": "处理 Euler-Cauchy 方程的重特征根与初值。",
            "instruction": "在 x>0 上解 x^2*y''-3x*y'+4y=0，且 y(1)=1、y'(1)=0。求 y(e)，只输出规范形式。",
            "expected": "-e^2",
            "topic": "differential-equation",
            "difficulty": 5,
        },
        {
            "slug": "math.ode-logistic-exact",
            "title": "非线性 Logistic 初值问题",
            "description": "分离变量求解非线性一阶方程并精确求值。",
            "instruction": "解 y'=y(1-y)，且 y(0)=1/3。求 y(ln(4))，只输出最简分数。",
            "expected": "2/3",
            "topic": "differential-equation",
            "difficulty": 5,
        },
        {
            "slug": "math.ode-linear-system-rotation",
            "title": "二维线性微分方程组",
            "description": "通过矩阵指数求解带旋转和指数增长的方程组。",
            "instruction": "方程组 x'=3x+4y、y'=-4x+3y，初值 (x(0),y(0))=(1,0)。求 t=pi/8 时的 (x,y)，严格输出 `(0,-e^(3*pi/8))` 形式。",
            "expected": "(0,-e^(3*pi/8))",
            "topic": "differential-equation",
            "difficulty": 5,
        },
        {
            "slug": "math.series-central-binomial",
            "title": "中心二项式无穷级数",
            "description": "计算含中心二项式系数的经典无穷级数。",
            "instruction": "计算从 n=1 到 ∞ 的级数 Σ 1/(n^2*C(2n,n))。用 pi 表示圆周率，只输出完全化简结果。",
            "expected": "pi^2/18",
            "topic": "infinite-series",
            "difficulty": 4,
        },
        {
            "slug": "math.series-alternating-harmonic",
            "title": "交错调和数级数",
            "description": "计算同时含调和数与交错因子的收敛级数。",
            "instruction": "令 H_n=Σ[k=1..n]1/k。计算 Σ[n=1..∞] (-1)^(n-1)*H_n/n。使用 pi 与 ln，严格输出 `pi^2/12-(ln(2)^2)/2`。",
            "expected": "pi^2/12-(ln(2)^2)/2",
            "topic": "infinite-series",
            "difficulty": 5,
        },
        {
            "slug": "math.series-endpoint-interval",
            "title": "幂级数端点判别",
            "description": "同时求收敛半径并逐一判断两个端点。",
            "instruction": "求幂级数 Σ[n=1..∞] (x-2)^n/(n*3^n) 的实数收敛区间。只用区间记号输出。",
            "expected": "[-1,5)",
            "topic": "infinite-series",
            "difficulty": 5,
        },
        {
            "slug": "math.series-cubic-geometric",
            "title": "三次加权几何级数",
            "description": "通过生成函数计算多项式加权几何级数。",
            "instruction": "计算 Σ[n=1..∞] n^3/2^n，只输出整数结果。",
            "expected": "26",
            "topic": "infinite-series",
            "difficulty": 5,
        },
        {
            "slug": "math.linear-algebra-hilbert-determinant",
            "title": "四阶 Hilbert 行列式",
            "description": "精确计算病态有理矩阵的行列式。",
            "instruction": "设 4x4 矩阵 H 的元素 H[i,j]=1/(i+j-1)，其中 i,j 从 1 开始。求 det(H)，只输出最简分数。",
            "expected": "1/6048000",
            "topic": "linear-algebra",
            "difficulty": 4,
        },
        {
            "slug": "math.linear-algebra-circulant-characteristic",
            "title": "循环矩阵特征多项式",
            "description": "由循环矩阵结构推导完整特征多项式。",
            "instruction": "矩阵 A=[[2,1,0,1],[1,2,1,0],[0,1,2,1],[1,0,1,2]]。求 det(lambda*I-A)，严格输出 `lambda*(lambda-2)^2*(lambda-4)`。",
            "expected": "lambda*(lambda-2)^2*(lambda-4)",
            "topic": "linear-algebra",
            "difficulty": 5,
        },
        {
            "slug": "math.linear-algebra-matrix-power",
            "title": "高次矩阵幂",
            "description": "利用递推或对角化精确计算二阶矩阵的高次幂。",
            "instruction": "令 A=[[2,1],[1,1]]。计算 A^10，严格输出无空格 JSON 二维数组。",
            "expected": "[[10946,6765],[6765,4181]]",
            "topic": "linear-algebra",
            "difficulty": 5,
        },
        {
            "slug": "math.linear-algebra-least-squares",
            "title": "精确最小二乘解",
            "description": "通过正规方程求过定线性系统的精确最小二乘参数。",
            "instruction": "设计矩阵 A 的四行为 (1,0),(1,1),(1,2),(1,3)，b=(1,2,2,5)^T。求使 ||A*beta-b||_2 最小的 beta=(beta0,beta1)，严格输出最简分数组成的有序对。",
            "expected": "(7/10,6/5)",
            "topic": "linear-algebra",
            "difficulty": 5,
        },
    ]
    cases: list[dict[str, Any]] = []
    for problem in problems:
        expected = str(problem["expected"])
        topic = str(problem["topic"])
        difficulty = int(problem["difficulty"])
        cases.append(
            {
                "slug": problem["slug"],
                "version": "2.3.0",
                "category": "reasoning",
                "title": problem["title"],
                "description": problem["description"],
                "instruction": problem["instruction"],
                "tools": [],
                "limits": {
                    "max_steps": 10,
                    "time_target_seconds": 900 if difficulty == 5 else 600,
                    "token_budget": 18000 if difficulty == 5 else 12000,
                },
                "validators": [_validator("exact_match", 90, expected=expected)],
                "tags": ["math", topic, "exact-symbolic", "deterministic"],
                "initial_files": {},
                "metadata": {
                    "demo_response": expected,
                    "difficulty": difficulty,
                    "estimated_minutes": 15 if difficulty == 5 else 10,
                    "capability": topic,
                },
            }
        )
    return cases


def _build_knowledge_work_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index in range(1, 16):
        target_number = 20 + index * 3
        target_id = f"INIT-{index:02d}-{target_number:03d}"
        portfolio = ["initiative_id,region,status,budget_k,quarter"]
        risks = ["# Risk register", "", "| initiative | severity | compliance |", "|---|---|---|"]
        owners: dict[str, dict[str, str]] = {}
        target_team = f"team-{(index % 6) + 1}"
        for item in range(1, 91):
            initiative_id = f"INIT-{index:02d}-{item:03d}"
            if item == target_number:
                region, status, budget, quarter = "APAC", "active", 900 + index, "Q4"
                severity, compliance, team = "critical", "approved", target_team
            else:
                region = ["EMEA", "AMER", "APAC"][item % 3]
                status = ["planned", "paused", "active"][item % 3]
                budget = 300 + item * 4
                quarter = ["Q1", "Q2", "Q3", "Q4"][item % 4]
                severity = ["low", "medium", "high", "critical"][item % 4]
                compliance = "approved" if item % 5 else "pending"
                team = f"team-{(item % 6) + 1}"
                if (
                    region == "APAC"
                    and status == "active"
                    and budget > 850
                    and quarter == "Q4"
                    and severity == "critical"
                    and compliance == "approved"
                    and team == target_team
                ):
                    compliance = "pending"
            portfolio.append(f"{initiative_id},{region},{status},{budget},{quarter}")
            risks.append(f"| {initiative_id} | {severity} | {compliance} |")
            owners[initiative_id] = {"team": team, "lead": f"lead-{item:03d}"}
        instruction = (
            "你正在进行季度项目组合审查。联合读取 `portfolio.csv`、`risk-register.md` "
            "和 `owners.json`，找出唯一同时满足以下条件的 initiative：APAC、active、"
            f"budget_k > 850、Q4、critical、approved，且负责团队为 `{target_team}`。"
            "只输出 initiative_id，不要解释。"
        )
        cases.append(
            {
                "slug": f"knowledge.cross-document-{index:03d}",
                "version": "2.0.0",
                "category": "knowledge-work",
                "title": f"跨文档项目审查 {index:02d}",
                "description": "在长表格、风险登记和组织映射间进行精确关联检索。",
                "instruction": instruction,
                "tools": ["filesystem", "search"],
                "limits": {
                    "max_steps": 18,
                    "timeout_seconds": 240,
                    "token_budget": 18000 + index * 500,
                },
                "validators": [_validator("exact_match", 92, expected=target_id)],
                "tags": ["long-context", "retrieval", "cross-document", "practical"],
                "initial_files": {
                    "portfolio.csv": "\n".join(portfolio) + "\n",
                    "risk-register.md": "\n".join(risks) + "\n",
                    "owners.json": json.dumps(owners, ensure_ascii=False, indent=2),
                },
                "metadata": {
                    "demo_response": target_id,
                    "difficulty": 4 if index <= 7 else 5,
                    "estimated_minutes": 12,
                    "capability": "long-context-retrieval",
                },
            }
        )
    return cases


def _build_data_analysis_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    regions = ["north", "south", "east", "west"]
    for index in range(1, 21):
        rows = ["order_id,region,gross,discount,refunded,customer"]
        totals = {region: 0 for region in regions}
        refunds = 0
        high_value = 0
        total_net = 0
        for item in range(1, 161):
            region = regions[(item + index) % len(regions)]
            gross = 80 + ((item * 37 + index * 19) % 920)
            discount = (item + index) % 5 * 10
            refunded = (item * index) % 17 == 0
            net = 0 if refunded else gross - discount
            totals[region] += net
            total_net += net
            refunds += int(refunded)
            high_value += int(net >= 750)
            rows.append(
                f"ORD-{index:02d}-{item:04d},{region},{gross},{discount},"
                f"{str(refunded).lower()},C-{(item * 13) % 97:03d}"
            )
        top_region = max(regions, key=lambda region: (totals[region], region))
        expected = {
            "total_net": total_net,
            "top_region": top_region,
            "refunds": refunds,
            "high_value_orders": high_value,
        }
        target = "deliverables/report.json"
        cases.append(
            {
                "slug": f"data.orders-analysis-{index:03d}",
                "version": "2.0.0",
                "category": "data-analysis",
                "title": f"订单经营分析 {index:02d}",
                "description": "从真实形态的 CSV 数据生成机器可验证的经营摘要。",
                "instruction": (
                    "分析 `orders.csv`。退款订单净额按 0 计算，否则净额为 gross-discount。"
                    f"创建 `{target}`，JSON 必须且只能包含 total_net、top_region、refunds、"
                    "high_value_orders；高价值定义为净额 >= 750，top_region 按净额合计选择。"
                ),
                "tools": ["filesystem", "search", "shell"],
                "limits": {
                    "max_steps": 24,
                    "timeout_seconds": 360,
                    "token_budget": 20000,
                    "network": "disabled",
                    "docker_image": "python:3.12-alpine",
                },
                "validators": [
                    _validator("file_exists", 10, path=target),
                    _validator("json_file", 82, path=target, expected=expected),
                    _validator("forbidden_paths", 5, paths=["expected*", ".git"]),
                ],
                "tags": ["csv", "analytics", "artifact", "partial-credit", "practical"],
                "initial_files": {"orders.csv": "\n".join(rows) + "\n"},
                "metadata": {
                    "demo_actions": [
                        {
                            "tool": "write_file",
                            "arguments": {
                                "path": target,
                                "content": json.dumps(expected, ensure_ascii=False),
                            },
                        }
                    ],
                    "demo_response": "经营分析报告已生成。",
                    "difficulty": 3 if index <= 8 else 4,
                    "estimated_minutes": 10,
                    "capability": "data-analysis",
                },
            }
        )
    return cases


def _build_agentic_workflow_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index in range(1, 16):
        files: dict[str, str] = {}
        tickets: list[tuple[int, int, str, int]] = []
        for item in range(1, 31):
            priority = ((item * 5 + index) % 4) + 1
            hours = ((item * 7 + index) % 12) + 1
            owner = f"team-{((item + index) % 5) + 1}"
            approved = (item + index) % 3 != 0
            ticket_id = f"TKT-{index:02d}-{item:03d}"
            files[f"requests/{ticket_id}.txt"] = (
                f"id={ticket_id}\npriority={priority}\nowner={owner}\n"
                f"hours={hours}\napproved={str(approved).lower()}\n"
            )
            if approved and priority >= 3:
                tickets.append((priority, hours, ticket_id, item))
        tickets.sort(key=lambda item: (-item[0], item[1], item[2]))
        summary = "ticket_id,priority,hours\n" + "".join(
            f"{ticket_id},{priority},{hours}\n" for priority, hours, ticket_id, _ in tickets
        )
        target = "deliverables/triage.csv"
        cases.append(
            {
                "slug": f"workflow.ticket-triage-{index:03d}",
                "version": "2.0.0",
                "category": "agentic-workflow",
                "title": f"多文件工单编排 {index:02d}",
                "description": "读取分散工单、应用业务规则并生成排序后的交付文件。",
                "instruction": (
                    "处理 `requests/` 下全部工单。仅保留 approved=true 且 priority>=3 的工单，"
                    "按 priority 降序、hours 升序、ticket_id 升序排列，创建 "
                    f"`{target}`，列严格为 ticket_id,priority,hours。不要修改源工单。"
                ),
                "tools": ["filesystem", "search"],
                "limits": {"max_steps": 30, "timeout_seconds": 300, "token_budget": 22000},
                "validators": [
                    _validator("file_exists", 10, path=target),
                    _validator("file_content", 82, path=target, expected=summary),
                    _validator("forbidden_paths", 4, paths=["requests/*.bak", ".git"]),
                ],
                "tags": ["multi-file", "workflow", "transformation", "practical"],
                "initial_files": files,
                "metadata": {
                    "demo_actions": [
                        {"tool": "write_file", "arguments": {"path": target, "content": summary}}
                    ],
                    "demo_response": "工单分流清单已生成。",
                    "difficulty": 3 if index <= 8 else 4,
                    "estimated_minutes": 10,
                    "capability": "multi-file-workflow",
                },
            }
        )
    return cases


def _build_advanced_coding_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index in range(1, 21):
        variant = index % 4
        factor = (index % 5) + 2
        if variant == 0:
            name = "shipping_quote"
            signature = "def shipping_quote(weight, zone, priority=False):"
            rule = f"基础价为 weight * {factor}；zone B 加 12，zone C 加 25；priority 再加 30"
            assertions = (
                f"assert shipping_quote(4, 'A') == {4 * factor}; "
                f"assert shipping_quote(4, 'B', True) == {4 * factor + 42}; "
                f"assert shipping_quote(0, 'C') == 25"
            )
            solution = (
                f"{signature}\n    extra = {{'A': 0, 'B': 12, 'C': 25}}[zone]\n"
                f"    return weight * {factor} + extra + (30 if priority else 0)\n"
            )
        elif variant == 1:
            name = "retry_delay"
            signature = "def retry_delay(attempt, base=2, cap=60):"
            rule = f"返回 min(cap, base * {factor} ** attempt)，attempt 从 0 开始"
            assertions = (
                f"assert retry_delay(0) == 2; assert retry_delay(2) == {2 * factor**2}; "
                "assert retry_delay(20) == 60"
            )
            solution = f"{signature}\n    return min(cap, base * {factor} ** attempt)\n"
        elif variant == 2:
            name = "sla_status"
            threshold = 20 + index
            signature = "def sla_status(minutes, premium=False):"
            rule = (
                f"premium 阈值为 {threshold} 分钟，普通阈值为 {threshold * 2} 分钟；"
                "小于等于阈值返回 'ok'，否则返回 'breach'"
            )
            assertions = (
                f"assert sla_status({threshold}, True) == 'ok'; "
                f"assert sla_status({threshold + 1}, True) == 'breach'; "
                f"assert sla_status({threshold * 2}, False) == 'ok'"
            )
            solution = (
                f"{signature}\n    limit = {threshold} if premium else {threshold * 2}\n"
                "    return 'ok' if minutes <= limit else 'breach'\n"
            )
        else:
            name = "invoice_total"
            rate = 5 + index
            signature = "def invoice_total(items, discount=0):"
            rule = f"先汇总 price*quantity，再减 discount，最后加 {rate}% 税并四舍五入到 2 位"
            assertions = (
                f"assert invoice_total([{{'price': 10, 'quantity': 2}}]) == {round(20 * (1 + rate / 100), 2)!r}; "
                f"assert invoice_total([{{'price': 7.5, 'quantity': 4}}], 5) == {round(25 * (1 + rate / 100), 2)!r}"
            )
            solution = (
                f"{signature}\n    subtotal = sum(x['price'] * x['quantity'] for x in items) - discount\n"
                f"    return round(subtotal * (1 + {rate} / 100), 2)\n"
            )
        initial = f'"""Business rules module."""\n\n{signature}\n    raise NotImplementedError\n'
        command = f'python -c "from src.rules import {name}; {assertions}"'
        cases.append(
            {
                "slug": f"coding.business-rules-{index:03d}",
                "version": "2.0.0",
                "category": "software-engineering",
                "title": f"实现业务规则模块 {index:02d}",
                "description": "在小型多文件项目中按业务规格实现边界行为并通过隐藏测试。",
                "instruction": (
                    f"实现 `src/rules.py` 中的 `{name}`。规则：{rule}。保持函数签名，"
                    "补充必要的输入处理，不要创建或修改 tests/。"
                ),
                "tools": ["filesystem", "search", "shell"],
                "limits": {
                    "max_steps": 32,
                    "timeout_seconds": 480,
                    "token_budget": 28000,
                    "network": "disabled",
                    "docker_image": "python:3.12-alpine",
                },
                "validators": [
                    _validator("command", 88, command=command),
                    _validator("forbidden_paths", 7, paths=["tests", ".git"]),
                ],
                "tags": ["python", "business-logic", "hidden-tests", "docker", "practical"],
                "initial_files": {
                    "src/__init__.py": "",
                    "src/rules.py": initial,
                    "README.md": f"# Rules task\n\nImplement `{name}` according to the task brief.\n",
                },
                "metadata": {
                    "demo_actions": [
                        {"tool": "write_file", "arguments": {"path": "src/rules.py", "content": solution}}
                    ],
                    "demo_response": "业务规则已实现并验证。",
                    "difficulty": 4 if index <= 12 else 5,
                    "estimated_minutes": 18,
                    "capability": "software-engineering",
                },
            }
        )
    return cases


def _build_security_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index in range(1, 16):
        variant = index % 3
        if variant == 0:
            title = "阻止路径穿越"
            instruction = (
                "实现 `security_utils.safe_join(root, user_path)`，返回解析后的 Path；"
                "绝对路径或逃逸 root 的路径必须抛出 ValueError。"
            )
            initial = "from pathlib import Path\n\ndef safe_join(root, user_path):\n    return Path(root) / user_path\n"
            solution = (
                "from pathlib import Path\n\ndef safe_join(root, user_path):\n"
                "    root = Path(root).resolve()\n    raw = Path(user_path)\n"
                "    if raw.is_absolute():\n        raise ValueError('absolute path')\n"
                "    target = (root / raw).resolve()\n"
                "    if not target.is_relative_to(root):\n        raise ValueError('path escape')\n"
                "    return target\n"
            )
            command = (
                'python -c "import tempfile; from pathlib import Path; '
                "from security_utils import safe_join; r=Path(tempfile.mkdtemp()); "
                "assert safe_join(r, 'a/b.txt') == (r/'a/b.txt').resolve(); "
                "ok=False; "
                "\ntry: safe_join(r, '../escape')\nexcept ValueError: ok=True\nassert ok" + '"'
            )
        elif variant == 1:
            title = "凭据日志脱敏"
            instruction = (
                "实现 `security_utils.redact_headers(headers)`，返回新字典；对大小写不敏感的 "
                "authorization、x-api-key、cookie 值替换为 ***，不得修改输入。"
            )
            initial = "def redact_headers(headers):\n    return dict(headers)\n"
            solution = (
                "def redact_headers(headers):\n    secrets = {'authorization', 'x-api-key', 'cookie'}\n"
                "    return {key: ('***' if key.lower() in secrets else value) "
                "for key, value in headers.items()}\n"
            )
            command = (
                'python -c "from security_utils import redact_headers; '
                "src={'Authorization':'Bearer secret','Accept':'json','X-API-Key':'abc'}; "
                "out=redact_headers(src); assert out == {'Authorization':'***','Accept':'json','X-API-Key':'***'}; "
                "assert src['Authorization'] == 'Bearer secret'" + '"'
            )
        else:
            title = "常量时间签名校验"
            instruction = (
                "修复 `security_utils.verify_signature(expected, provided)`，使用标准库常量时间比较，"
                "兼容 str 输入，不得使用 == 比较密钥。"
            )
            initial = "def verify_signature(expected, provided):\n    return expected == provided\n"
            solution = (
                "import hmac\n\ndef verify_signature(expected, provided):\n"
                "    return hmac.compare_digest(expected.encode(), provided.encode())\n"
            )
            command = (
                'python -c "from pathlib import Path; from security_utils import verify_signature; '
                "assert verify_signature('abc','abc'); assert not verify_signature('abc','abd'); "
                "assert 'compare_digest' in Path('security_utils.py').read_text()" + '"'
            )
        cases.append(
            {
                "slug": f"security.hardening-{index:03d}",
                "version": "2.0.0",
                "category": "security",
                "title": f"{title} {index:02d}",
                "description": "修复可复现的应用安全缺陷并通过攻击型隐藏测试。",
                "instruction": instruction + " 不要修改验证环境或创建 tests/。",
                "tools": ["filesystem", "search", "shell"],
                "limits": {
                    "max_steps": 35,
                    "timeout_seconds": 480,
                    "token_budget": 30000,
                    "network": "disabled",
                    "docker_image": "python:3.12-alpine",
                },
                "validators": [
                    _validator("command", 90, command=command),
                    _validator("forbidden_paths", 5, paths=["tests", ".git"]),
                ],
                "tags": ["security", "python", "hidden-tests", "docker", "practical"],
                "initial_files": {"security_utils.py": initial, "SECURITY.md": instruction + "\n"},
                "metadata": {
                    "demo_actions": [
                        {
                            "tool": "write_file",
                            "arguments": {"path": "security_utils.py", "content": solution},
                        }
                    ],
                    "demo_response": "安全缺陷已修复。",
                    "difficulty": 4 if index <= 9 else 5,
                    "estimated_minutes": 20,
                    "capability": "security-engineering",
                },
            }
        )
    return cases


def _build_planning_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    scenarios = [
        "支付平台从单体迁移到可回滚的模块化架构",
        "客服团队在六周内上线带人工兜底的 AI 分流",
        "制造企业整合三个区域互相冲突的库存数据",
        "医疗预约系统在不中断服务的情况下升级身份认证",
        "跨境电商建立可审计的价格异常处置流程",
    ]
    schema = {
        "type": "object",
        "required": ["scenario_id", "assumptions", "phases", "risks", "success_metrics"],
        "properties": {
            "scenario_id": {"type": "string"},
            "assumptions": {"type": "array", "minItems": 3, "items": {"type": "string"}},
            "phases": {
                "type": "array",
                "minItems": 3,
                "items": {
                    "type": "object",
                    "required": ["name", "exit_criteria", "rollback"],
                    "properties": {
                        "name": {"type": "string"},
                        "exit_criteria": {"type": "array", "minItems": 1},
                        "rollback": {"type": "string", "minLength": 10},
                    },
                },
            },
            "risks": {"type": "array", "minItems": 4},
            "success_metrics": {"type": "array", "minItems": 3},
        },
    }
    for index in range(1, 16):
        scenario_id = f"PLAN-{index:03d}"
        scenario = scenarios[(index - 1) % len(scenarios)]
        cases.append(
            {
                "slug": f"planning.delivery-plan-{index:03d}",
                "version": "2.0.0",
                "category": "planning",
                "title": f"高约束交付规划 {index:02d}",
                "description": "在信息不完整和高风险约束下产出可执行、可回滚、可衡量的计划。",
                "instruction": (
                    f"场景：{scenario}。预算上限 {80 + index * 5} 万，周期 {6 + index % 5} 周，"
                    "不得安排全量停机，任何自动决策必须保留人工兜底。只输出一个 JSON 对象，"
                    f"scenario_id 必须为 `{scenario_id}`；列出假设、至少三个阶段（每阶段含退出标准"
                    "和回滚方案）、至少四项风险及至少三项量化成功指标。"
                ),
                "tools": [],
                "limits": {
                    "max_steps": 8,
                    "timeout_seconds": 300,
                    "token_budget": 24000,
                },
                "validators": [
                    _validator("contains", 10, text=scenario_id),
                    _validator("json_schema", 35, schema=schema),
                    _validator(
                        "ai_rubric",
                        55,
                        criteria=[
                            "计划可执行且阶段依赖清晰",
                            "退出标准和成功指标可以客观验证",
                            "风险、人工兜底和回滚策略具体",
                            "在预算和周期约束内做出明确取舍",
                        ],
                    ),
                ],
                "tags": ["planning", "decision-making", "json", "judge", "frontier"],
                "initial_files": {},
                "metadata": {
                    "demo_response": json.dumps(
                        {
                            "scenario_id": scenario_id,
                            "assumptions": ["资源已批准", "接口可用", "业务代表可参与"],
                            "phases": [
                                {
                                    "name": f"phase-{phase}",
                                    "exit_criteria": ["验收通过"],
                                    "rollback": "恢复上一稳定版本并保留审计记录",
                                }
                                for phase in range(1, 4)
                            ],
                            "risks": ["进度", "数据", "安全", "采用率"],
                            "success_metrics": ["可用率>=99.9%", "错误率<1%", "回滚<30分钟"],
                        },
                        ensure_ascii=False,
                    ),
                    "difficulty": 5,
                    "estimated_minutes": 18,
                    "capability": "planning-and-judgment",
                },
            }
        )
    return cases


def _build_legacy_ultra_catalog() -> list[dict[str, Any]]:
    event_store_initial = textwrap.dedent(
        '''
        import json
        import sqlite3

        class ConcurrencyError(RuntimeError):
            pass

        class EventStore:
            def __init__(self, path):
                self.path = str(path)
                connection = sqlite3.connect(self.path)
                connection.execute("CREATE TABLE IF NOT EXISTS events(stream TEXT, version INTEGER, payload TEXT)")
                connection.commit()
                connection.close()

            def append(self, stream_id, expected_version, events, command_id):
                # Deliberately incomplete: not atomic, not idempotent and unsafe under concurrency.
                connection = sqlite3.connect(self.path)
                current = connection.execute(
                    "SELECT COALESCE(MAX(version), -1) FROM events WHERE stream=?", (stream_id,)
                ).fetchone()[0]
                if current != expected_version:
                    raise ConcurrencyError((current, expected_version))
                versions = []
                for payload in events:
                    current += 1
                    connection.execute(
                        "INSERT INTO events(stream,version,payload) VALUES (?,?,?)",
                        (stream_id, current, json.dumps(payload)),
                    )
                    versions.append(current)
                connection.commit()
                connection.close()
                return versions

            def read(self, stream_id):
                connection = sqlite3.connect(self.path)
                rows = connection.execute(
                    "SELECT version,payload FROM events WHERE stream=? ORDER BY version", (stream_id,)
                ).fetchall()
                connection.close()
                return [{"version": row[0], "payload": json.loads(row[1])} for row in rows]

            def save_snapshot(self, stream_id, version, state):
                raise NotImplementedError

            def load_snapshot(self, stream_id):
                return None
        '''
    ).strip() + "\n"
    event_store_solution = textwrap.dedent(
        '''
        import hashlib
        import json
        import sqlite3

        class ConcurrencyError(RuntimeError):
            pass

        def _canonical(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        class EventStore:
            def __init__(self, path):
                self.path = str(path)
                with self._connect() as connection:
                    connection.executescript("""
                    CREATE TABLE IF NOT EXISTS events(
                        stream TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
                        PRIMARY KEY(stream, version));
                    CREATE TABLE IF NOT EXISTS commands(
                        command_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS snapshots(
                        stream TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL,
                        checksum TEXT NOT NULL);
                    """)

            def _connect(self):
                connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=30000")
                return connection

            def append(self, stream_id, expected_version, events, command_id):
                fingerprint = hashlib.sha256(
                    _canonical({"stream": stream_id, "expected": expected_version, "events": events}).encode()
                ).hexdigest()
                connection = self._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    duplicate = connection.execute(
                        "SELECT fingerprint,result FROM commands WHERE command_id=?", (command_id,)
                    ).fetchone()
                    if duplicate:
                        if duplicate[0] != fingerprint:
                            raise ValueError("command_id reused with different payload")
                        connection.commit()
                        return json.loads(duplicate[1])
                    current = connection.execute(
                        "SELECT COALESCE(MAX(version),-1) FROM events WHERE stream=?", (stream_id,)
                    ).fetchone()[0]
                    if current != expected_version:
                        raise ConcurrencyError(f"expected {expected_version}, actual {current}")
                    versions = []
                    for payload in events:
                        current += 1
                        connection.execute(
                            "INSERT INTO events(stream,version,payload) VALUES (?,?,?)",
                            (stream_id, current, _canonical(payload)),
                        )
                        versions.append(current)
                    connection.execute(
                        "INSERT INTO commands(command_id,fingerprint,result) VALUES (?,?,?)",
                        (command_id, fingerprint, _canonical(versions)),
                    )
                    connection.commit()
                    return versions
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

            def read(self, stream_id):
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT version,payload FROM events WHERE stream=? ORDER BY version", (stream_id,)
                    ).fetchall()
                return [{"version": row[0], "payload": json.loads(row[1])} for row in rows]

            def save_snapshot(self, stream_id, version, state):
                payload = _canonical(state)
                checksum = hashlib.sha256(payload.encode()).hexdigest()
                with self._connect() as connection:
                    current = connection.execute(
                        "SELECT COALESCE(MAX(version),-1) FROM events WHERE stream=?", (stream_id,)
                    ).fetchone()[0]
                    if version > current:
                        raise ValueError("snapshot is ahead of stream")
                    connection.execute(
                        "INSERT INTO snapshots(stream,version,state,checksum) VALUES (?,?,?,?) "
                        "ON CONFLICT(stream) DO UPDATE SET version=excluded.version,state=excluded.state,"
                        "checksum=excluded.checksum WHERE excluded.version>=snapshots.version",
                        (stream_id, version, payload, checksum),
                    )

            def load_snapshot(self, stream_id):
                with self._connect() as connection:
                    row = connection.execute(
                        "SELECT version,state,checksum FROM snapshots WHERE stream=?", (stream_id,)
                    ).fetchone()
                if not row:
                    return None
                if hashlib.sha256(row[1].encode()).hexdigest() != row[2]:
                    raise ValueError("snapshot checksum mismatch")
                return {"version": row[0], "state": json.loads(row[1])}
        '''
    ).strip() + "\n"
    event_validator = textwrap.dedent(
        '''
        import tempfile
        import threading
        from pathlib import Path
        from event_store import ConcurrencyError, EventStore

        root = Path(tempfile.mkdtemp())
        store = EventStore(root / "events.db")
        assert store.append("account-1", -1, [{"type":"opened"},{"type":"credited","n":2}], "cmd-1") == [0, 1]
        assert store.append("account-1", -1, [{"type":"opened"},{"n":2,"type":"credited"}], "cmd-1") == [0, 1]
        assert len(store.read("account-1")) == 2
        try:
            store.append("account-1", 1, [{"type":"wrong"}], "cmd-1")
            raise AssertionError("command payload reuse was accepted")
        except ValueError:
            pass
        try:
            store.append("account-1", 0, [{"type":"bad-version"}], "cmd-2")
            raise AssertionError("optimistic concurrency was not enforced")
        except ConcurrencyError:
            pass

        errors = []
        def worker(worker_id):
            for index in range(20):
                while True:
                    current = len(store.read("hot")) - 1
                    try:
                        store.append("hot", current, [{"worker":worker_id,"index":index}], f"{worker_id}-{index}")
                        break
                    except ConcurrencyError:
                        continue
                    except Exception as exc:
                        errors.append(exc)
                        return
        threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        assert not errors, errors
        events = store.read("hot")
        assert len(events) == 120
        assert [item["version"] for item in events] == list(range(120))
        store.save_snapshot("hot", 119, {"count":120,"nested":{"ok":True}})
        assert store.load_snapshot("hot") == {"version":119,"state":{"count":120,"nested":{"ok":True}}}
        print("ULTRA_EVENT_STORE_OK")
        '''
    ).strip() + "\n"

    tasks = [
        {"id": "A", "duration": 4, "cpu": 2, "gpu": 0, "deps": []},
        {"id": "B", "duration": 5, "cpu": 2, "gpu": 0, "deps": []},
        {"id": "C", "duration": 6, "cpu": 2, "gpu": 1, "deps": ["A"]},
        {"id": "D", "duration": 4, "cpu": 2, "gpu": 0, "deps": ["A"]},
        {"id": "E", "duration": 5, "cpu": 2, "gpu": 1, "deps": ["B"]},
        {"id": "F", "duration": 4, "cpu": 3, "gpu": 0, "deps": ["C"]},
        {"id": "G", "duration": 3, "cpu": 2, "gpu": 0, "deps": ["D", "E"]},
        {"id": "H", "duration": 6, "cpu": 2, "gpu": 1, "deps": ["E"]},
        {"id": "I", "duration": 5, "cpu": 2, "gpu": 0, "deps": ["F"]},
        {"id": "J", "duration": 4, "cpu": 2, "gpu": 0, "deps": ["G"]},
        {"id": "K", "duration": 3, "cpu": 3, "gpu": 1, "deps": ["H", "I"]},
        {"id": "L", "duration": 5, "cpu": 2, "gpu": 0, "deps": ["J"]},
        {"id": "M", "duration": 4, "cpu": 1, "gpu": 1, "deps": ["K"]},
        {"id": "N", "duration": 3, "cpu": 4, "gpu": 0, "deps": ["L", "M"]},
    ]
    schedule = {
        "A": 0, "B": 0, "C": 4, "D": 4, "E": 8, "F": 10, "G": 14,
        "H": 14, "I": 17, "J": 20, "K": 22, "L": 25, "M": 25, "N": 30,
    }
    schedule_payload = [{"id": task["id"], "start": schedule[task["id"]]} for task in tasks]
    scheduler_validator = textwrap.dedent(
        '''
        import json
        from pathlib import Path

        instance = json.loads(Path("instance.json").read_text(encoding="utf-8"))
        schedule = json.loads(Path("deliverables/schedule.json").read_text(encoding="utf-8-sig"))
        assert isinstance(schedule, list)
        starts = {item["id"]: int(item["start"]) for item in schedule}
        tasks = {item["id"]: item for item in instance["tasks"]}
        assert set(starts) == set(tasks)
        ends = {task_id: starts[task_id] + task["duration"] for task_id, task in tasks.items()}
        for task_id, task in tasks.items():
            assert starts[task_id] >= task.get("release", 0)
            assert all(ends[dep] <= starts[task_id] for dep in task.get("deps", []))
        makespan = max(ends.values())
        for tick in range(makespan):
            active = [task for task_id, task in tasks.items() if starts[task_id] <= tick < ends[task_id]]
            assert sum(task["cpu"] for task in active) <= instance["capacity"]["cpu"]
            assert sum(task["gpu"] for task in active) <= instance["capacity"]["gpu"]
        assert makespan <= instance["target_makespan"], (makespan, instance["target_makespan"])
        print(f"ULTRA_SCHEDULER_OK makespan={makespan}")
        '''
    ).strip() + "\n"

    common_policy = {
        "max_attempts": 3,
        "pass_threshold": 85,
        "multipliers": [1.0, 0.85, 0.70],
        "preserve_workspace": True,
    }
    return [
        {
            "slug": "ultra.event-store-crash-consistency-001",
            "version": "3.0.0",
            "category": "ultra-engineering",
            "title": "ULTRA · 崩溃一致性事件存储",
            "description": "在并发、幂等重放与快照完整性约束下修复 SQLite 事件存储。",
            "instruction": (
                "修复 `event_store.py`，保持公开 API 不变。实现原子批量追加、乐观并发、全局 command_id "
                "幂等、规范 JSON、线程/多连接安全以及带校验和的单调快照。不得通过修改验证脚本或跳过断言完成。"
            ),
            "tools": ["filesystem", "search", "shell"],
            "limits": {
                "max_steps": 80,
                "time_target_seconds": 1800,
                "max_runtime_seconds": 7200,
                "token_budget": 120000,
                "network": "disabled",
                "docker_image": "python:3.12-alpine",
            },
            "validators": [
                _validator("file_exists", 5, path="event_store.py"),
                _validator(
                    "command",
                    85,
                    command="python ultra_validate.py",
                    critical=True,
                ),
                _validator("file_content", 5, path="ultra_validate.py", expected=event_validator),
                _validator("forbidden_paths", 5, paths=[".git"]),
            ],
            "tags": ["ultra", "sqlite", "concurrency", "idempotency", "fault-tolerance"],
            "initial_files": {
                "event_store.py": event_store_initial,
                "ultra_validate.py": event_validator,
            },
            "attempt_policy": {
                **common_policy,
                "hints": [
                    "重点检查事务开始时机、唯一约束、command_id 指纹，以及 SQLite busy_timeout/WAL。",
                    "使用 BEGIN IMMEDIATE 串行化写事务；commands 表同时保存规范化输入指纹和版本结果；快照保存 SHA-256。",
                ],
            },
            "metadata": {
                "difficulty": 6,
                "tier": "ultra",
                "estimated_minutes": 45,
                "capability": "crash-consistent-concurrent-engineering",
                "demo_actions": [
                    {"tool": "write_file", "arguments": {"path": "event_store.py", "content": event_store_solution}}
                ],
                "demo_response": "事件存储已完成并通过并发与幂等验证。",
            },
        },
        {
            "slug": "ultra.resource-scheduler-001",
            "version": "3.0.0",
            "category": "ultra-planning",
            "title": "ULTRA · 多资源约束调度",
            "description": "在依赖、CPU/GPU 容量和最优工期约束下生成可证明有效的调度计划。",
            "instruction": (
                "读取 `instance.json`，生成 `deliverables/schedule.json`。必须为每个任务给出整数 start，"
                "满足全部依赖与逐时刻 CPU/GPU 容量，并达到 target_makespan。请自行编写求解或搜索程序并验证结果。"
            ),
            "tools": ["filesystem", "search", "shell"],
            "limits": {
                "max_steps": 70,
                "time_target_seconds": 1500,
                "max_runtime_seconds": 7200,
                "token_budget": 100000,
                "network": "disabled",
                "docker_image": "python:3.12-alpine",
            },
            "validators": [
                _validator("file_exists", 5, path="deliverables/schedule.json"),
                _validator(
                    "command",
                    85,
                    command="python verify_schedule.py",
                    critical=True,
                ),
                _validator("file_content", 3, path="verify_schedule.py", expected=scheduler_validator),
                _validator(
                    "file_content",
                    2,
                    path="instance.json",
                    expected=json.dumps(
                        {"capacity": {"cpu": 4, "gpu": 2}, "target_makespan": 33, "tasks": tasks},
                        ensure_ascii=False,
                        indent=2,
                    ),
                ),
                _validator("forbidden_paths", 5, paths=[".git"]),
            ],
            "tags": ["ultra", "planning", "constraint-solving", "optimization"],
            "initial_files": {
                "instance.json": json.dumps(
                    {"capacity": {"cpu": 4, "gpu": 2}, "target_makespan": 33, "tasks": tasks},
                    ensure_ascii=False,
                    indent=2,
                ),
                "verify_schedule.py": scheduler_validator,
            },
            "attempt_policy": {
                **common_policy,
                "hints": [
                    "先计算关键路径，再用事件时刻而不是逐任务贪心；CPU 是主要瓶颈。",
                    "可从 A/B 同时在 0 开始，C/D 在 A 后并行；用回溯或 CP-SAT 风格的离散搜索把 makespan 压到 33。",
                ],
            },
            "metadata": {
                "difficulty": 6,
                "tier": "ultra",
                "estimated_minutes": 40,
                "capability": "multi-resource-constraint-optimization",
                "demo_actions": [
                    {
                        "tool": "write_file",
                        "arguments": {
                            "path": "deliverables/schedule.json",
                            "content": json.dumps(schedule_payload, ensure_ascii=False, indent=2),
                        },
                    }
                ],
                "demo_response": "已生成满足容量、依赖和目标工期的调度计划。",
            },
        },
    ]


def _build_scheduler_ultra_instance(
    instance_id: str,
    *,
    horizon: int,
    task_count: int,
    capacity: dict[str, int],
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a deterministic, reference-backed multi-mode RCPSP instance."""
    generator = random.Random(seed)
    resources = ("cpu", "gpu", "memory", "io")
    occupancy = {key: [0] * horizon for key in resources}
    planned: dict[str, dict[str, Any]] = {}

    anchor_id = "ZZ"
    anchor_mode = {
        "id": "balanced",
        "duration": 5,
        "cpu": 1,
        "gpu": 0,
        "memory": 1,
        "io": 0,
        "energy": 10,
    }
    anchor_start = horizon - anchor_mode["duration"]
    for key in resources:
        for tick in range(anchor_start, horizon):
            occupancy[key][tick] += int(anchor_mode[key])
    planned[anchor_id] = {"start": anchor_start, "mode": anchor_mode}

    def fits(start: int, mode: dict[str, Any]) -> bool:
        end = start + int(mode["duration"])
        return all(
            occupancy[key][tick] + int(mode[key]) <= capacity[key]
            for key in resources
            for tick in range(start, end)
        )

    def reserve(start: int, mode: dict[str, Any]) -> None:
        end = start + int(mode["duration"])
        for key in resources:
            for tick in range(start, end):
                occupancy[key][tick] += int(mode[key])

    for index in range(1, task_count):
        task_id = f"T{index:02d}"
        for _attempt in range(3000):
            duration = generator.randint(3, 8)
            balanced = {
                "id": "balanced",
                "duration": duration,
                "cpu": generator.randint(1, min(4, capacity["cpu"])),
                "gpu": generator.choices([0, 1, 2], [5, 4, 1])[0],
                "memory": generator.randint(2, min(7, capacity["memory"])),
                "io": generator.choices([0, 1, 2], [2, 5, 2])[0],
            }
            balanced["energy"] = duration * (
                balanced["cpu"] + 2 * balanced["gpu"] + max(1, balanced["io"])
            )
            candidates = [
                start
                for start in range(0, horizon - duration + 1)
                if fits(start, balanced)
            ]
            if not candidates:
                continue
            ranked: list[tuple[float, int]] = []
            for start in candidates:
                fill = sum(
                    occupancy[key][tick] / capacity[key]
                    for key in resources
                    for tick in range(start, start + duration)
                )
                ranked.append((fill + generator.random() * 1.5, start))
            start = max(ranked)[1]
            reserve(start, balanced)
            planned[task_id] = {"start": start, "mode": balanced}
            break
        else:  # pragma: no cover - fixed seeds are covered by catalog tests
            raise RuntimeError(f"Unable to generate scheduler task {instance_id}/{task_id}")

    tasks: list[dict[str, Any]] = []
    mutex_groups: dict[str, list[str]] = {f"M{index}": [] for index in range(1, 5)}
    normal_ids = [task_id for task_id in planned if task_id != anchor_id]
    for task_id in normal_ids:
        start = int(planned[task_id]["start"])
        balanced = dict(planned[task_id]["mode"])
        duration = int(balanced["duration"])
        fast = {
            "id": "fast",
            "duration": max(2, duration - 1),
            "cpu": min(capacity["cpu"], int(balanced["cpu"]) + 1),
            "gpu": min(
                capacity["gpu"],
                int(balanced["gpu"])
                + int(balanced["gpu"] == 0 and generator.random() < 0.45),
            ),
            "memory": min(capacity["memory"], int(balanced["memory"]) + 2),
            "io": min(capacity["io"], int(balanced["io"]) + 1),
            "energy": int(int(balanced["energy"]) * 1.45) + 3,
        }
        eco = {
            "id": "eco",
            "duration": duration + 2,
            "cpu": max(1, int(balanced["cpu"]) - 1),
            "gpu": max(0, int(balanced["gpu"]) - 1),
            "memory": max(1, int(balanced["memory"]) - 1),
            "io": max(0, int(balanced["io"]) - 1),
            "energy": max(1, int(int(balanced["energy"]) * 0.63)),
        }
        predecessors = [
            candidate
            for candidate in normal_ids
            if candidate != task_id
            and int(planned[candidate]["start"])
            + int(planned[candidate]["mode"]["duration"])
            <= start
        ]
        generator.shuffle(predecessors)
        dependency_count = generator.choices([0, 1, 2], [3, 5, 2])[0]
        task: dict[str, Any] = {
            "id": task_id,
            "modes": [fast, balanced, eco],
            "release": max(0, start - generator.randint(3, 12)),
            "deadline": min(
                horizon,
                start
                + duration
                + generator.choices([0, 2, 4, 7, 10], [2, 3, 3, 2, 1])[0],
            ),
            "deps": predecessors[:dependency_count],
        }
        if generator.random() < 0.4:
            end = start + duration
            available_groups = []
            for group, members in mutex_groups.items():
                if all(
                    start
                    >= int(planned[member]["start"])
                    + int(planned[member]["mode"]["duration"])
                    or end <= int(planned[member]["start"])
                    for member in members
                ):
                    available_groups.append(group)
            if available_groups:
                group = generator.choice(available_groups)
                mutex_groups[group].append(task_id)
                task["mutex_group"] = group
        tasks.append(task)

    tasks.append(
        {
            "id": anchor_id,
            "modes": [anchor_mode],
            "release": anchor_start,
            "deadline": horizon,
            "deps": [],
        }
    )
    energy = sum(int(planned[task["id"]]["mode"]["energy"]) for task in tasks)
    instance = {
        "id": instance_id,
        "capacity": capacity,
        "target_makespan": horizon,
        "energy_budget": energy + max(5, energy // 20),
        "lower_bound": {
            "type": "release_plus_min_duration",
            "task": anchor_id,
            "value": horizon,
        },
        "tasks": tasks,
    }
    reference = {
        "id": instance_id,
        "schedule": [
            {"id": task["id"], "start": planned[task["id"]]["start"], "mode": "balanced"}
            for task in tasks
        ],
    }
    return instance, reference


@lru_cache(maxsize=1)
def _build_scheduler_ultra_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    profiles = [
        ("instance-1", 46, 24, {"cpu": 8, "gpu": 3, "memory": 18, "io": 4}, 731),
        ("instance-2", 54, 28, {"cpu": 10, "gpu": 4, "memory": 22, "io": 5}, 947),
        ("instance-3", 62, 32, {"cpu": 12, "gpu": 4, "memory": 26, "io": 6}, 1217),
    ]
    instances: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    for instance_id, horizon, count, capacity, seed in profiles:
        instance, reference = _build_scheduler_ultra_instance(
            instance_id,
            horizon=horizon,
            task_count=count,
            capacity=capacity,
            seed=seed,
        )
        instances.append(instance)
        references.append(reference)
    return {"instances": instances}, {"instances": references}


def _build_ultra_catalog_v4() -> list[dict[str, Any]]:
    event_store_initial = textwrap.dedent(
        '''
        import json
        import sqlite3

        class ConcurrencyError(RuntimeError):
            pass

        class IntegrityError(RuntimeError):
            pass

        class EventStore:
            def __init__(self, path):
                self.path = str(path)
                connection = sqlite3.connect(self.path)
                connection.executescript("""
                CREATE TABLE IF NOT EXISTS events(
                    stream TEXT, version INTEGER, payload TEXT, checksum TEXT);
                CREATE TABLE IF NOT EXISTS commands(
                    command_id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS snapshots(
                    stream TEXT, version INTEGER, state TEXT, checksum TEXT);
                """)
                connection.commit()
                connection.close()

            def append(self, stream_id, expected_version, events, command_id):
                # Deliberately unsafe: each event is committed separately and command replay is ignored.
                connection = sqlite3.connect(self.path)
                current = connection.execute(
                    "SELECT COALESCE(MAX(version), -1) FROM events WHERE stream=?", (stream_id,)
                ).fetchone()[0]
                if current != expected_version:
                    raise ConcurrencyError((current, expected_version))
                versions = []
                for payload in events:
                    current += 1
                    connection.execute(
                        "INSERT INTO events(stream,version,payload) VALUES (?,?,?)",
                        (stream_id, current, json.dumps(payload)),
                    )
                    connection.commit()
                    versions.append(current)
                connection.close()
                return versions

            def read(self, stream_id):
                connection = sqlite3.connect(self.path)
                rows = connection.execute(
                    "SELECT version,payload FROM events WHERE stream=? ORDER BY version", (stream_id,)
                ).fetchall()
                connection.close()
                return [{"version": row[0], "payload": json.loads(row[1])} for row in rows]

            def save_snapshot(self, stream_id, version, state):
                connection = sqlite3.connect(self.path)
                connection.execute(
                    "INSERT INTO snapshots(stream,version,state) VALUES (?,?,?)",
                    (stream_id, version, json.dumps(state)),
                )
                connection.commit()
                connection.close()

            def load_snapshot(self, stream_id):
                return None
        '''
    ).strip() + "\n"
    event_store_solution = textwrap.dedent(
        '''
        import hashlib
        import json
        import sqlite3

        class ConcurrencyError(RuntimeError):
            pass

        class IntegrityError(RuntimeError):
            pass

        def _canonical(value):
            return json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )

        def _event_checksum(stream, version, payload, previous):
            material = f"{stream}\\0{version}\\0{previous}\\0{payload}".encode("utf-8")
            return hashlib.sha256(material).hexdigest()

        class EventStore:
            def __init__(self, path):
                self.path = str(path)
                connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
                try:
                    connection.execute("PRAGMA busy_timeout=30000")
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.execute("PRAGMA synchronous=FULL")
                    connection.execute("BEGIN EXCLUSIVE")
                    columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(events)").fetchall()
                    }
                    if columns and not {"stream", "version", "payload", "checksum"} <= columns:
                        connection.execute("ALTER TABLE events RENAME TO events_legacy")
                        self._create_events(connection)
                        previous_by_stream = {}
                        rows = connection.execute(
                            "SELECT stream,version,payload FROM events_legacy ORDER BY stream,version"
                        ).fetchall()
                        for stream, version, raw_payload in rows:
                            payload = _canonical(json.loads(raw_payload))
                            previous = previous_by_stream.get(stream, "")
                            checksum = _event_checksum(stream, version, payload, previous)
                            connection.execute(
                                "INSERT INTO events(stream,version,payload,checksum) VALUES (?,?,?,?)",
                                (stream, version, payload, checksum),
                            )
                            previous_by_stream[stream] = checksum
                        connection.execute("DROP TABLE events_legacy")
                    else:
                        self._create_events(connection)
                    connection.executescript("""
                    CREATE TABLE IF NOT EXISTS commands(
                        command_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL,
                        result TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS snapshots(
                        stream TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        state TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        PRIMARY KEY(stream, version));
                    """)
                    connection.execute("PRAGMA user_version=4")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

            @staticmethod
            def _create_events(connection):
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS events(
                        stream TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        PRIMARY KEY(stream, version))
                """)

            def _connect(self):
                connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA synchronous=FULL")
                return connection

            def append(self, stream_id, expected_version, events, command_id):
                if not isinstance(events, list):
                    raise TypeError("events must be a list")
                canonical_events = [_canonical(item) for item in events]
                fingerprint = hashlib.sha256(
                    _canonical(
                        {"stream": stream_id, "expected": expected_version, "events": events}
                    ).encode("utf-8")
                ).hexdigest()
                connection = self._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    duplicate = connection.execute(
                        "SELECT fingerprint,result FROM commands WHERE command_id=?", (command_id,)
                    ).fetchone()
                    if duplicate:
                        if duplicate[0] != fingerprint:
                            raise ValueError("command_id reused with different input")
                        connection.commit()
                        return json.loads(duplicate[1])
                    latest = connection.execute(
                        "SELECT version,checksum FROM events WHERE stream=? "
                        "ORDER BY version DESC LIMIT 1",
                        (stream_id,),
                    ).fetchone()
                    current = latest[0] if latest else -1
                    previous = latest[1] if latest else ""
                    if current != expected_version:
                        raise ConcurrencyError(f"expected {expected_version}, actual {current}")
                    versions = []
                    for payload in canonical_events:
                        current += 1
                        checksum = _event_checksum(stream_id, current, payload, previous)
                        connection.execute(
                            "INSERT INTO events(stream,version,payload,checksum) VALUES (?,?,?,?)",
                            (stream_id, current, payload, checksum),
                        )
                        versions.append(current)
                        previous = checksum
                    connection.execute(
                        "INSERT INTO commands(command_id,fingerprint,result) VALUES (?,?,?)",
                        (command_id, fingerprint, _canonical(versions)),
                    )
                    connection.commit()
                    return versions
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

            def read(self, stream_id):
                connection = self._connect()
                try:
                    connection.execute("BEGIN")
                    rows = connection.execute(
                        "SELECT version,payload,checksum FROM events "
                        "WHERE stream=? ORDER BY version",
                        (stream_id,),
                    ).fetchall()
                    previous = ""
                    output = []
                    for expected, (version, payload, checksum) in enumerate(rows):
                        if version != expected:
                            raise IntegrityError("event version gap")
                        if _event_checksum(stream_id, version, payload, previous) != checksum:
                            raise IntegrityError("event checksum mismatch")
                        output.append({"version": version, "payload": json.loads(payload)})
                        previous = checksum
                    connection.commit()
                    return output
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

            def save_snapshot(self, stream_id, version, state):
                payload = _canonical(state)
                checksum = hashlib.sha256(
                    f"{stream_id}\\0{version}\\0{payload}".encode("utf-8")
                ).hexdigest()
                connection = self._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    current = connection.execute(
                        "SELECT COALESCE(MAX(version),-1) FROM events WHERE stream=?",
                        (stream_id,),
                    ).fetchone()[0]
                    if version < 0 or version > current:
                        raise ValueError("snapshot version is outside the stream")
                    latest = connection.execute(
                        "SELECT MAX(version) FROM snapshots WHERE stream=?", (stream_id,)
                    ).fetchone()[0]
                    if latest is not None and version < latest:
                        raise ConcurrencyError("snapshot version regression")
                    existing = connection.execute(
                        "SELECT state,checksum FROM snapshots WHERE stream=? AND version=?",
                        (stream_id, version),
                    ).fetchone()
                    if existing:
                        if existing != (payload, checksum):
                            raise ValueError("snapshot version reused with different state")
                    else:
                        connection.execute(
                            "INSERT INTO snapshots(stream,version,state,checksum) VALUES (?,?,?,?)",
                            (stream_id, version, payload, checksum),
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

            def load_snapshot(self, stream_id):
                connection = self._connect()
                try:
                    current = connection.execute(
                        "SELECT COALESCE(MAX(version),-1) FROM events WHERE stream=?",
                        (stream_id,),
                    ).fetchone()[0]
                    rows = connection.execute(
                        "SELECT version,state,checksum FROM snapshots "
                        "WHERE stream=? AND version<=? ORDER BY version DESC",
                        (stream_id, current),
                    ).fetchall()
                finally:
                    connection.close()
                for version, state, checksum in rows:
                    actual = hashlib.sha256(
                        f"{stream_id}\\0{version}\\0{state}".encode("utf-8")
                    ).hexdigest()
                    if actual == checksum:
                        return {"version": version, "state": json.loads(state)}
                if rows:
                    raise IntegrityError("no valid snapshot remains")
                return None
        '''
    ).strip() + "\n"
    event_public_smoke = textwrap.dedent(
        '''
        import tempfile
        from pathlib import Path
        from event_store import ConcurrencyError, EventStore

        store = EventStore(Path(tempfile.mkdtemp()) / "smoke.db")
        assert store.append("orders", -1, [{"type":"created"},{"n":2}], "cmd-1") == [0, 1]
        assert store.append("orders", -1, [{"type":"created"},{"n":2}], "cmd-1") == [0, 1]
        assert [item["version"] for item in store.read("orders")] == [0, 1]
        try:
            store.append("orders", 0, [{"bad":True}], "cmd-2")
            raise AssertionError("expected ConcurrencyError")
        except ConcurrencyError:
            pass
        store.save_snapshot("orders", 0, {"status":"created"})
        store.save_snapshot("orders", 1, {"status":"ready"})
        assert store.load_snapshot("orders") == {"version":1,"state":{"status":"ready"}}
        print("PUBLIC_EVENT_STORE_SMOKE_OK")
        '''
    ).strip() + "\n"
    event_private_validator = textwrap.dedent(
        '''
        import json
        import multiprocessing as mp
        import os
        import sqlite3
        import tempfile
        import time
        from pathlib import Path
        from event_store import ConcurrencyError, EventStore, IntegrityError

        root = Path(tempfile.mkdtemp())

        store = EventStore(root / "canonical.db")
        expected = [{"z":1,"nested":{"b":2,"a":"值"}},{"number":3.5}]
        assert store.append("s", -1, expected, "same-command") == [0, 1]
        replay = [{"nested":{"a":"值","b":2},"z":1},{"number":3.5}]
        assert store.append("s", -1, replay, "same-command") == [0, 1]
        try:
            store.append("other", -1, expected, "same-command")
            raise AssertionError("cross-stream command reuse accepted")
        except ValueError:
            pass
        before = store.read("s")
        try:
            store.append("s", 1, [{"ok":1},{"bad":{1,2}}], "bad-json")
            raise AssertionError("non-JSON payload accepted")
        except (TypeError, ValueError):
            pass
        assert store.read("s") == before

        def hot_writer(path, worker, errors):
            try:
                local = EventStore(path)
                for index in range(10):
                    while True:
                        current = len(local.read("hot")) - 1
                        try:
                            local.append(
                                "hot", current,
                                [{"worker":worker,"index":index,"part":0},
                                 {"worker":worker,"index":index,"part":1}],
                                f"hot-{worker}-{index}",
                            )
                            break
                        except ConcurrencyError:
                            continue
            except Exception as exc:
                errors.put(repr(exc))

        context = mp.get_context("fork")
        hot_path = root / "hot.db"
        EventStore(hot_path)
        errors = context.Queue()
        workers = [context.Process(target=hot_writer, args=(hot_path, i, errors)) for i in range(8)]
        [worker.start() for worker in workers]
        [worker.join(60) for worker in workers]
        assert all(not worker.is_alive() and worker.exitcode == 0 for worker in workers)
        assert errors.empty(), errors.get() if not errors.empty() else None
        hot = EventStore(hot_path).read("hot")
        assert len(hot) == 160
        assert [item["version"] for item in hot] == list(range(160))

        def replay_writer(path, output):
            try:
                result = EventStore(path).append("one", -1, [{"once":True}], "global-once")
                output.put(("ok", result))
            except Exception as exc:
                output.put(("error", repr(exc)))

        replay_path = root / "replay.db"
        EventStore(replay_path)
        output = context.Queue()
        replayers = [context.Process(target=replay_writer, args=(replay_path, output)) for _ in range(6)]
        [worker.start() for worker in replayers]
        [worker.join(30) for worker in replayers]
        replay_results = [output.get(timeout=2) for _ in replayers]
        assert replay_results == [("ok", [0])] * 6, replay_results
        assert len(EventStore(replay_path).read("one")) == 1

        snap_path = root / "snapshots.db"
        snapshots = EventStore(snap_path)
        snapshots.append("account", -1, [{"n":n} for n in range(6)], "seed-snapshots")
        snapshots.save_snapshot("account", 2, {"balance":3})
        snapshots.save_snapshot("account", 5, {"balance":6})
        connection = sqlite3.connect(snap_path)
        connection.execute(
            "UPDATE snapshots SET state='corrupt' WHERE stream='account' AND version=5"
        )
        connection.commit()
        connection.close()
        assert snapshots.load_snapshot("account") == {"version":2,"state":{"balance":3}}
        try:
            snapshots.save_snapshot("account", 1, {"balance":2})
            raise AssertionError("snapshot regression accepted")
        except (ConcurrencyError, ValueError):
            pass

        tamper_path = root / "tamper.db"
        tamper = EventStore(tamper_path)
        tamper.append("audit", -1, [{"secure":True}], "audit-1")
        connection = sqlite3.connect(tamper_path)
        connection.execute("UPDATE events SET payload='{}' WHERE stream='audit' AND version=0")
        connection.commit()
        connection.close()
        try:
            tamper.read("audit")
            raise AssertionError("event corruption was not detected")
        except IntegrityError:
            pass

        legacy_path = root / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.execute("CREATE TABLE events(stream TEXT,version INTEGER,payload TEXT)")
        connection.execute("INSERT INTO events VALUES ('legacy',0,'{\\\"old\\\":true}')")
        connection.commit()
        connection.close()
        legacy = EventStore(legacy_path)
        assert legacy.read("legacy") == [{"version":0,"payload":{"old":True}}]
        assert legacy.append("legacy", 0, [{"new":True}], "legacy-command") == [1]

        def crash_writer(path, ready):
            local = EventStore(path)
            blob = "x" * 4096
            batch = [{"index":index,"blob":blob} for index in range(30000)]
            ready.set()
            local.append("crash", -1, batch, "crash-command")

        crash_path = root / "crash.db"
        EventStore(crash_path)
        ready = context.Event()
        doomed = context.Process(target=crash_writer, args=(crash_path, ready))
        doomed.start()
        assert ready.wait(20)
        time.sleep(0.04)
        assert doomed.is_alive(), "crash workload finished before the kill point"
        doomed.kill()
        doomed.join(20)
        connection = sqlite3.connect(crash_path)
        count = connection.execute("SELECT COUNT(*) FROM events WHERE stream='crash'").fetchone()[0]
        connection.close()
        assert count == 0, f"partial batch survived process kill: {count} rows"
        recovered = EventStore(crash_path)
        assert recovered.append("crash", -1, [{"recovered":True}], "after-crash") == [0]
        assert recovered.read("crash")[0]["payload"] == {"recovered":True}

        print("ULTRA_EVENT_STORE_V4_OK multiprocess=8 crash=rollback migration=ok")
        '''
    ).strip() + "\n"

    scheduler_payload, scheduler_reference = _build_scheduler_ultra_payloads()
    instance_text = json.dumps(scheduler_payload, ensure_ascii=False, indent=2)
    reference_text = json.dumps(scheduler_reference, ensure_ascii=False, indent=2)
    instance_hash = hashlib.sha256(
        json.dumps(
            scheduler_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    scheduler_validator_template = textwrap.dedent(
        '''
        import hashlib
        import json
        from pathlib import Path

        expected_hash = "__EXPECTED_HASH__"
        instance_bytes = Path("instances.json").read_bytes()
        payload = json.loads(instance_bytes.decode("utf-8-sig"))
        canonical_instance = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if expected_hash != "PUBLIC":
            assert hashlib.sha256(canonical_instance).hexdigest() == expected_hash, "instances.json changed"
        answer = json.loads(Path("deliverables/schedule.json").read_text(encoding="utf-8-sig"))
        assert isinstance(answer, dict) and isinstance(answer.get("instances"), list)
        answers = {item["id"]: item for item in answer["instances"]}
        instances = {item["id"]: item for item in payload["instances"]}
        assert set(answers) == set(instances), "instance ids differ"

        summary = []
        for instance_id, instance in instances.items():
            rows = answers[instance_id].get("schedule")
            assert isinstance(rows, list), f"{instance_id}: schedule must be a list"
            assert all(isinstance(row, dict) for row in rows)
            tasks = {task["id"]: task for task in instance["tasks"]}
            assert len(rows) == len(tasks), f"{instance_id}: duplicate or missing rows"
            choices = {row["id"]: row for row in rows}
            assert set(choices) == set(tasks), f"{instance_id}: task ids differ"
            selected = {}
            starts = {}
            ends = {}
            energy = 0
            for task_id, task in tasks.items():
                row = choices[task_id]
                start = row.get("start")
                assert isinstance(start, int) and not isinstance(start, bool) and start >= 0
                modes = {mode["id"]: mode for mode in task["modes"]}
                mode_id = row.get("mode")
                assert mode_id in modes, f"{instance_id}/{task_id}: invalid mode"
                mode = modes[mode_id]
                starts[task_id] = start
                ends[task_id] = start + mode["duration"]
                selected[task_id] = mode
                energy += mode["energy"]
                assert start >= task.get("release", 0), f"{instance_id}/{task_id}: release"
                assert ends[task_id] <= task["deadline"], f"{instance_id}/{task_id}: deadline"
            assert energy <= instance["energy_budget"], f"{instance_id}: energy {energy}"
            for task_id, task in tasks.items():
                assert all(
                    ends[dependency] <= starts[task_id] for dependency in task.get("deps", [])
                ), f"{instance_id}/{task_id}: dependency"
            makespan = max(ends.values())
            assert makespan <= instance["target_makespan"], (
                instance_id, makespan, instance["target_makespan"]
            )
            for tick in range(makespan):
                active = [
                    task_id for task_id in tasks if starts[task_id] <= tick < ends[task_id]
                ]
                for resource, limit in instance["capacity"].items():
                    used = sum(selected[task_id][resource] for task_id in active)
                    assert used <= limit, f"{instance_id} tick={tick} {resource}={used}>{limit}"
            groups = {}
            for task_id, task in tasks.items():
                if task.get("mutex_group"):
                    groups.setdefault(task["mutex_group"], []).append(task_id)
            for group, members in groups.items():
                ordered = sorted(members, key=lambda task_id: starts[task_id])
                assert all(
                    ends[left] <= starts[right] for left, right in zip(ordered, ordered[1:])
                ), f"{instance_id}: mutex {group}"
            summary.append(f"{instance_id}:{makespan}/{energy}")
        print("ULTRA_SCHEDULER_V4_OK " + " ".join(summary))
        '''
    ).strip() + "\n"
    scheduler_public_validator = scheduler_validator_template.replace(
        "__EXPECTED_HASH__", "PUBLIC"
    )
    scheduler_private_validator = scheduler_validator_template.replace(
        "__EXPECTED_HASH__", instance_hash
    )

    common_policy = {
        "max_attempts": 3,
        "pass_threshold": 85,
        "multipliers": [1.0, 0.85, 0.70],
        "preserve_workspace": True,
    }
    return [
        {
            "slug": "ultra.event-store-crash-consistency-002",
            "version": "4.0.0",
            "category": "ultra-engineering",
            "title": "ULTRA · 崩溃一致性事件存储 II",
            "description": "跨进程竞争、强杀恢复、迁移与哈希链完整性下实现持久化事件存储。",
            "instruction": (
                "阅读 `SPEC.md` 并修复 `event_store.py`，保持 EventStore 的四个公开方法不变。"
                "公开 smoke 只覆盖基础契约；最终评分使用任务结束后注入的私有随机/故障验证器。"
                "不得修改规格或以跳过校验、识别验证环境等方式完成任务。"
            ),
            "tools": ["filesystem", "search", "shell"],
            "limits": {
                "max_steps": 140,
                "time_target_seconds": 2700,
                "max_runtime_seconds": 14400,
                "validator_timeout_seconds": 360,
                "token_budget": 250000,
                "network": "disabled",
                "docker_image": "python:3.12-alpine",
            },
            "validators": [
                _validator("file_exists", 4, path="event_store.py"),
                _validator(
                    "command",
                    91,
                    command="python {private_root}/validate_event_store.py",
                    private_files={"validate_event_store.py": event_private_validator},
                    critical=True,
                ),
                _validator(
                    "file_content", 2, path="public_smoke.py", expected=event_public_smoke
                ),
                _validator("forbidden_paths", 3, paths=[".git", ".agentbench-private-*"]),
            ],
            "tags": [
                "ultra",
                "sqlite",
                "multiprocessing",
                "crash-consistency",
                "migration",
                "hash-chain",
            ],
            "initial_files": {
                "event_store.py": event_store_initial,
                "public_smoke.py": event_public_smoke,
                "SPEC.md": (
                    "# Durable EventStore v4\n\n"
                    "Implement `append`, `read`, `save_snapshot`, and `load_snapshot` using only the Python "
                    "standard library and SQLite. Required semantics:\n\n"
                    "- atomic all-or-nothing batches under process kill; WAL + FULL durability; no partial visibility;\n"
                    "- optimistic expected-version checks and gap-free versions per stream;\n"
                    "- global command_id idempotency using a canonical input fingerprint; conflicting reuse raises ValueError;\n"
                    "- canonical UTF-8 JSON (`sort_keys`, compact separators, `allow_nan=False`);\n"
                    "- safe concurrent use by threads, processes and independent EventStore instances;\n"
                    "- event integrity hash chain: read detects payload/version tampering and raises IntegrityError;\n"
                    "- snapshot history is monotonic and idempotent; load chooses the newest valid snapshot and falls "
                    "back when a newer row is corrupt;\n"
                    "- migrate the legacy `events(stream, version, payload)` table without data loss;\n"
                    "- schema compatibility: tables are named `events`, `commands`, `snapshots`; snapshots expose "
                    "`stream, version, state, checksum`.\n\n"
                    "Run `python public_smoke.py` locally. Private tests add multi-process contention, corruption and "
                    "mid-transaction process termination.\n"
                ),
            },
            "attempt_policy": {
                **common_policy,
                "hints": [
                    "把规范化与指纹计算放在事务前；写入使用 BEGIN IMMEDIATE、唯一约束和显式 rollback。保留多版快照，读取时逐版校验。",
                    "事件校验和应包含 stream/version/previous_hash/canonical_payload。初始化需在 EXCLUSIVE 迁移中重建旧表；每个进程独立连接并设置 busy_timeout。",
                ],
            },
            "metadata": {
                "difficulty": 6,
                "tier": "ultra",
                "estimated_minutes": 75,
                "capability": "crash-consistent-multiprocess-engineering",
                "private_validation": True,
                "demo_actions": [
                    {
                        "tool": "write_file",
                        "arguments": {"path": "event_store.py", "content": event_store_solution},
                    }
                ],
                "demo_response": "事件存储已实现，并通过崩溃恢复、迁移和多进程一致性验证。",
            },
        },
        {
            "slug": "ultra.multi-mode-resource-scheduler-002",
            "version": "4.0.0",
            "category": "ultra-planning",
            "title": "ULTRA · 多模式多资源约束调度",
            "description": "同时求解三个带模式选择、四类容量、能耗、依赖、时间窗和互斥组的 RCPSP 实例。",
            "instruction": (
                "读取 `instances.json`，生成 `deliverables/schedule.json`。三个实例都必须选择任务模式并给出整数开始时间，"
                "同时满足 release/deadline、依赖、CPU/GPU/内存/IO 容量、互斥组、总能耗和 target_makespan。"
                "可自行编写回溯、分支定界或约束传播求解器；`python check_schedule.py` 可验证候选解。"
            ),
            "tools": ["filesystem", "search", "shell"],
            "limits": {
                "max_steps": 130,
                "time_target_seconds": 2400,
                "max_runtime_seconds": 14400,
                "validator_timeout_seconds": 240,
                "token_budget": 220000,
                "network": "disabled",
                "docker_image": "python:3.12-alpine",
            },
            "validators": [
                _validator("file_exists", 4, path="deliverables/schedule.json"),
                _validator(
                    "command",
                    91,
                    command="python {private_root}/verify_schedule.py",
                    private_files={"verify_schedule.py": scheduler_private_validator},
                    critical=True,
                ),
                _validator("file_content", 3, path="instances.json", expected=instance_text),
                _validator(
                    "file_content",
                    1,
                    path="check_schedule.py",
                    expected=scheduler_public_validator,
                ),
                _validator("forbidden_paths", 1, paths=[".git", ".agentbench-private-*"]),
            ],
            "tags": [
                "ultra",
                "multi-mode-rcpsp",
                "constraint-solving",
                "branch-and-bound",
                "multi-instance",
            ],
            "initial_files": {
                "instances.json": instance_text,
                "check_schedule.py": scheduler_public_validator,
                "FORMAT.md": (
                    "Write `{\"instances\":[{\"id\":\"instance-1\",\"schedule\":["
                    "{\"id\":\"T01\",\"start\":0,\"mode\":\"balanced\"}, ...]}, ...]}` "
                    "to `deliverables/schedule.json`. Every task appears exactly once.\n"
                ),
            },
            "attempt_policy": {
                **common_policy,
                "hints": [
                    "先按 deadline-release 窗口和依赖做约束传播，再联合选择 fast/balanced/eco；逐时刻四资源和能耗必须同时剪枝。每个实例的 ZZ 提供可证明的工期下界。",
                    "建议实现事件时刻分支定界：优先最小剩余窗口任务，枚举模式与可行开始时间，并对互斥组、资源 compulsory part、剩余能耗做前向检查。三个实例可分别求解。",
                ],
            },
            "metadata": {
                "difficulty": 6,
                "tier": "ultra",
                "estimated_minutes": 70,
                "capability": "multi-mode-multi-resource-constraint-optimization",
                "private_validation": True,
                "instance_count": 3,
                "task_count": 84,
                "reference_schedule": scheduler_reference,
                "demo_actions": [
                    {
                        "tool": "write_file",
                        "arguments": {
                            "path": "deliverables/schedule.json",
                            "content": reference_text,
                        },
                    }
                ],
                "demo_response": "已生成三个实例的多模式调度，并通过全部资源、能耗和时间窗约束。",
            },
        },
    ]


def build_ultra_catalog() -> list[dict[str, Any]]:
    """Return the current Ultra catalog; v4 remains only as a reference-answer source."""
    from .ultra_v5 import build_ultra_catalog_v5

    event_solution = _build_ultra_catalog_v4()[0]["metadata"]["demo_actions"][0]["arguments"][
        "content"
    ]
    return build_ultra_catalog_v5(event_solution)


def seed_builtin_data(database: Database) -> None:
    now = utc_now()
    if not database.fetch_one("SELECT id FROM models WHERE id = ?", (MOCK_MODEL_ID,)):
        database.execute(
            "INSERT INTO models(id, name, provider, model_name, api_style, settings_json, "
            "enabled, builtin, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
            (
                MOCK_MODEL_ID,
                "AgentBench Demo Model",
                "builtin",
                "mock-v1",
                "mock",
                json.dumps({"temperature": 0, "max_tokens": 4096}),
                now,
                now,
            ),
        )

    runners = [
        (
            UNIFIED_RUNNER_ID,
            "统一 Agent Harness",
            "unified",
            None,
            [],
            "你是参加 AgentBench 公平评测的执行 Agent。按任务要求使用工具并提交结果。",
            ["filesystem", "search", "shell"],
            True,
        ),
        (
            CODEX_RUNNER_ID,
            "Codex CLI",
            "codex_cli",
            "codex",
            [
                "exec",
                "--json",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "workspace-write",
                "--model",
                "{model_name}",
                "{prompt}",
            ],
            "",
            ["native-cli"],
            True,
        ),
        (
            CLAUDE_RUNNER_ID,
            "Claude Code CLI",
            "claude_code_cli",
            "claude",
            [
                "--print",
                "--output-format",
                "json",
                "--no-session-persistence",
                "--permission-mode",
                "auto",
                "--effort",
                "medium",
                "--model",
                "{model_name}",
                "{prompt}",
            ],
            "",
            ["native-cli"],
            True,
        ),
        (
            OPENCODE_RUNNER_ID,
            "OpenCode CLI",
            "opencode_cli",
            "opencode",
            [
                "run",
                "--format",
                "json",
                "--auto",
                "--model",
                "{model_name}",
                "{prompt}",
            ],
            "",
            ["native-cli", "filesystem", "shell"],
            True,
        ),
        (
            REASONIX_RUNNER_ID,
            "Reasonix CLI",
            "reasonix_cli",
            "reasonix",
            [
                "run",
                "--output-format",
                "json",
                "--permission-mode",
                "auto",
                "--model",
                "{model_name}",
                "{prompt}",
            ],
            "",
            ["native-cli", "filesystem", "shell"],
            True,
        ),
        (
            GEMINI_RUNNER_ID,
            "Gemini CLI",
            "gemini_cli",
            "gemini",
            [
                "--output-format",
                "stream-json",
                "--model",
                "{model_name}",
                "--prompt",
                "{prompt}",
            ],
            "",
            ["native-cli", "filesystem", "shell"],
            True,
        ),
        (
            AIDER_RUNNER_ID,
            "Aider CLI",
            "aider_cli",
            "aider",
            [
                "--yes",
                "--no-git",
                "--no-auto-commits",
                "--model",
                "{model_name}",
                "--message",
                "{prompt}",
            ],
            "",
            ["native-cli", "filesystem", "shell"],
            True,
        ),
        (
            KIMI_RUNNER_ID,
            "Kimi Code CLI",
            "kimi_code_cli",
            "kimi",
            [
                "--print",
                "--output-format",
                "stream-json",
                "--yolo",
                "--model",
                "{model_name}",
                "--prompt",
                "{prompt}",
            ],
            "",
            ["native-cli", "filesystem", "shell"],
            True,
        ),
        (
            QODER_RUNNER_ID,
            "Qoder CLI",
            "qoder_cli",
            "qoderclicn",
            [
                "--print",
                "--output-format",
                "json",
                "--dangerously-skip-permissions",
                "{prompt}",
            ],
            "",
            ["native-cli", "filesystem", "shell"],
            False,
        ),
        (
            CUSTOM_RUNNER_ID,
            "自定义命令 Agent",
            "command",
            None,
            ["{prompt}"],
            "",
            ["native-cli"],
            True,
        ),
    ]
    for runner_id, name, kind, executable, args, prompt, tools, override in runners:
        existing = database.fetch_one(
            "SELECT id,builtin FROM agent_runners WHERE id = ?", (runner_id,)
        )
        if existing and existing["builtin"]:
            # Built-in Runner definitions are application code, not user configuration.
            # Refresh them on every startup so an in-place desktop upgrade receives
            # corrected non-interactive flags.  User-owned state (enabled, env and
            # limits) and all historical run foreign keys remain untouched.
            database.execute(
                "UPDATE agent_runners SET name=?,runner_type=?,executable=?,args_json=?,"
                "system_prompt=?,tools_json=?,model_override_supported=?,updated_at=? "
                "WHERE id=? AND builtin=1",
                (
                    name,
                    kind,
                    executable,
                    json.dumps(args, ensure_ascii=False),
                    prompt,
                    json.dumps(tools),
                    int(override),
                    now,
                    runner_id,
                ),
            )
            continue
        if existing:
            continue
        database.execute(
            "INSERT INTO agent_runners(id, name, runner_type, executable, args_json, "
            "system_prompt, tools_json, limits_json, model_override_supported, enabled, builtin, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
            (
                runner_id,
                name,
                kind,
                executable,
                json.dumps(args, ensure_ascii=False),
                prompt,
                json.dumps(tools),
                json.dumps({"max_steps": 40, "max_runtime_seconds": 7200}),
                int(override),
                now,
                now,
            ),
        )

    case_ids: list[str] = []
    base_cases = build_catalog()
    ultra_cases = build_ultra_catalog()
    math_cases_by_lane = build_builtin_math_cases()
    math_closed_cases = [item["definition"] for item in math_cases_by_lane["closed-book"]]
    math_tool_cases = [item["definition"] for item in math_cases_by_lane["tool-augmented"]]
    cases = base_cases + ultra_cases + math_closed_cases + math_tool_cases
    for definition in cases:
        case_id = stable_id("case", f"{definition['slug']}@{definition['version']}")
        case_ids.append(case_id)
        if database.fetch_one("SELECT id FROM test_cases WHERE id = ?", (case_id,)):
            database.execute(
                "UPDATE test_cases SET category=?,title=?,description=?,definition_json=?,enabled=1 "
                "WHERE id=? AND builtin=1",
                (
                    definition["category"],
                    definition["title"],
                    definition["description"],
                    json.dumps(definition, ensure_ascii=False),
                    case_id,
                ),
            )
            continue
        database.execute(
            "INSERT INTO test_cases(id, slug, version, category, title, description, "
            "definition_json, builtin, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)",
            (
                case_id,
                definition["slug"],
                definition["version"],
                definition["category"],
                definition["title"],
                definition["description"],
                json.dumps(definition, ensure_ascii=False),
                now,
            ),
        )

    placeholders = ",".join("?" for _ in case_ids)
    database.execute(
        f"UPDATE test_cases SET enabled=0 WHERE builtin=1 AND id NOT IN ({placeholders})",
        tuple(case_ids),
    )

    base_case_ids = case_ids[: len(base_cases)]
    ultra_start = len(base_cases)
    math_closed_start = ultra_start + len(ultra_cases)
    math_tool_start = math_closed_start + len(math_closed_cases)
    ultra_case_ids = case_ids[ultra_start:math_closed_start]
    math_closed_ids = case_ids[math_closed_start:math_tool_start]
    math_tool_ids = case_ids[math_tool_start:]
    quick_v2 = (
        base_case_ids[:4]
        + base_case_ids[25:29]
        + base_case_ids[50:54]
        + base_case_ids[100:104]
        + base_case_ids[135:139]
    )
    practical_v2 = (
        base_case_ids[100:115]
        + base_case_ids[115:135]
        + base_case_ids[135:150]
        + base_case_ids[150:165]
        + base_case_ids[170:180]
    )
    frontier_v2 = (
        base_case_ids[107:115]
        + base_case_ids[162:170]
        + base_case_ids[179:185]
        + base_case_ids[185:200]
    )
    reasoning_focus = base_case_ids[25:50]
    planning_focus = base_case_ids[185:200]
    coding_focus = base_case_ids[150:170]
    slug_to_case_id = {
        definition["slug"]: case_id for definition, case_id in zip(cases, case_ids, strict=True)
    }

    def _ncre_paper_members(paper_no: str) -> list[str]:
        return [
            slug_to_case_id[f"ncre.office.paper{paper_no}.{section}"]
            for section in ("choice", "word", "excel", "ppt")
        ]

    def _case_needs_docker(definition: dict[str, Any]) -> bool:
        limits = definition.get("limits") or {}
        if limits.get("docker_image"):
            return True
        return any(
            validator.get("type") in {"command", "command_metrics"}
            for validator in definition.get("validators") or []
        )

    def _select_gauntlet_members() -> list[str]:
        d5_ids: list[str] = []
        d4_buckets: dict[str, list[str]] = {
            category: []
            for category in ("data-analysis", "agentic-workflow", "security", "reasoning")
        }
        for definition, case_id in zip(base_cases, base_case_ids, strict=True):
            if definition["category"] == "office-exam":
                continue
            difficulty = (definition.get("metadata") or {}).get("difficulty")
            if difficulty == 5:
                d5_ids.append(case_id)
            elif difficulty == 4:
                bucket = d4_buckets.get(definition["category"])
                if bucket is not None:
                    bucket.append(case_id)
        members = list(d5_ids)
        for category, quota in (
            ("data-analysis", 4),
            ("agentic-workflow", 2),
            ("security", 1),
            ("reasoning", 1),
        ):
            members.extend(d4_buckets[category][:quota])
        return members

    def _select_gauntlet_lite_members() -> list[str]:
        # 免 Docker 池按域配额抽取；V3 规划使用内置约束验证器，无需 Docker。
        # reasoning 取 20、planning/knowledge-work 各取 15，保持 50 题高难快速摸底。
        buckets: dict[str, list[str]] = {
            category: []
            for category in ("reasoning", "planning", "knowledge-work", "agentic-workflow")
        }
        for definition, case_id in zip(base_cases, base_case_ids, strict=True):
            metadata = definition.get("metadata") or {}
            if int(metadata.get("difficulty") or 0) < 4:
                continue
            if definition["category"] == "office-exam" or _case_needs_docker(definition):
                continue
            bucket = buckets.get(definition["category"])
            if bucket is not None:
                bucket.append(case_id)
        members: list[str] = []
        for category, quota in (
            ("reasoning", 20),
            ("planning", 15),
            ("knowledge-work", 15),
            ("agentic-workflow", 7),
        ):
            members.extend(buckets[category][:quota])
        return members

    gauntlet_members = _select_gauntlet_members()
    gauntlet_docker_count = sum(
        _case_needs_docker(definition)
        for definition, case_id in zip(base_cases, base_case_ids, strict=True)
        if case_id in set(gauntlet_members)
    )
    gauntlet_lite_members = _select_gauntlet_lite_members()

    suites = [
        (FULL_SUITE_ID, "AgentBench V1 完整基准", "100 个四领域基础测试", "1.0.0", base_case_ids[:100]),
        (
            SMOKE_SUITE_ID,
            "AgentBench V1 快速体验",
            "无需 Docker 的 12 个快速测试",
            "1.0.0",
            base_case_ids[:4] + base_case_ids[25:29] + base_case_ids[50:54],
        ),
        (
            V2_QUICK_SUITE_ID,
            "V2 快速上手",
            "20 个零费用、无需 Docker 的格式、推理、检索与多文件工作流测试",
            "2.0.0",
            quick_v2,
        ),
        (
            PRACTICAL_SUITE_ID,
            "V2 实战能力基准",
            "75 个贴近工作场景的检索、数据、工作流、编码与安全测试",
            "2.0.0",
            practical_v2,
        ),
        (
            FRONTIER_SUITE_ID,
            "V2 极限压力基准",
            "37 个难度 5 的长上下文、复杂编码、安全与高约束规划任务",
            "2.0.0",
            frontier_v2,
        ),
        (
            V2_FULL_SUITE_ID,
            "AgentBench V2 全量基准",
            "212 个从基础稳定性到前沿 Agent 能力的完整分层测试",
            "2.0.0",
            base_case_ids,
        ),
        (
            ULTRA_SUITE_ID,
            "AgentBench Ultra 极限挑战",
            "两道三轮自适应极限挑战：崩溃一致性事件存储与多模式多资源调度",
            "4.0.0",
            ultra_case_ids,
        ),
        (
            REASONING_SUITE_ID,
            "专项 · 推理计算",
            "25 道纯推理题：多步算术、积分、求导、微分方程、无穷级数与线性代数",
            "2.4.1",
            reasoning_focus,
        ),
        (
            PLANNING_SUITE_ID,
            "专项 · 规划决策",
            "15 道纯规划题：依赖、资源、风险、时间窗与高约束交付决策",
            "2.4.1",
            planning_focus,
        ),
        (
            CODING_SUITE_ID,
            "专项 · 编码工程",
            "20 道纯编码题：多文件业务规则实现、边界处理与自动化验证",
            "2.4.1",
            coding_focus,
        ),
        (
            MATH_2025_CLOSED_SUITE_ID,
            "2025 考研数学（一）· 闭卷推理",
            "用户提供的 2025 数学一真题与解析，22 题、满分 150 分；禁用工具的纯推理赛道。",
            "2025.1",
            math_closed_ids,
        ),
        (
            MATH_2025_TOOL_SUITE_ID,
            "2025 考研数学（一）· 工具增强",
            "用户提供的 2025 数学一真题与解析，22 题、满分 150 分；允许 Agent 使用本地工具。",
            "2025.1",
            math_tool_ids,
        ),
        (
            NCRE_OFFICE_SUITE_ID,
            "NCRE二级 MS Office 真题卷1",
            "NCRE 二级 MS Office 高级应用 2016年3月真题第1套：选择题 + Word/Excel/PowerPoint 操作题",
            "2.5.0",
            _ncre_paper_members("01"),
        ),
        (
            NCRE_OFFICE_PAPER02_SUITE_ID,
            "NCRE二级 MS Office 真题卷2",
            "NCRE 二级 MS Office 高级应用经典题库第2套（多期无纸化考试流转使用，重构版）："
            "选择题 + Word/Excel/PowerPoint 操作题，需 Docker",
            "2.5.0",
            _ncre_paper_members("02"),
        ),
        (
            NCRE_OFFICE_PAPER03_SUITE_ID,
            "NCRE二级 MS Office 真题卷3",
            "NCRE 二级 MS Office 高级应用经典题库第4套（多期无纸化考试流转使用，重构版）："
            "选择题 + Word/Excel/PowerPoint 操作题，需 Docker",
            "2.5.0",
            _ncre_paper_members("03"),
        ),
        (
            GAUNTLET_SUITE_ID,
            "高难快速摸底",
            f"{len(gauntlet_members)} 道难度 5 为主、难度 4 补足的高难快速摸底：覆盖 reasoning、"
            "planning、knowledge-work、software-engineering、security、data-analysis、"
            f"agentic-workflow 七域；基础指令与工具域无高难题故不覆盖；含 {gauntlet_docker_count} "
            "道需 Docker 题；适合新发布大模型快速测水平",
            "2.6.0",
            gauntlet_members,
        ),
        (
            GAUNTLET_LITE_SUITE_ID,
            "高难快速摸底 · 免 Docker",
            f"{len(gauntlet_lite_members)} 道难度≥4 且完全免 Docker 的高难快速摸底：覆盖 "
            "reasoning、planning、knowledge-work 三域（software-engineering、security、"
            "data-analysis 与高难 agentic-workflow 依赖 Docker，基础指令与工具域无高难题，"
            "故均不覆盖）；适合新发布大模型在无 Docker 环境下快速测水平",
            "3.0.0",
            gauntlet_lite_members,
        ),
    ]
    for suite_id, name, description, version, members in suites:
        if not database.fetch_one("SELECT id FROM test_suites WHERE id = ?", (suite_id,)):
            database.execute(
                "INSERT INTO test_suites(id, name, description, version, builtin, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (suite_id, name, description, version, now),
            )
        database.execute(
            "UPDATE test_suites SET name=?,description=?,version=? WHERE id=? AND builtin=1",
            (name, description, version, suite_id),
        )
        database.execute("DELETE FROM suite_cases WHERE suite_id=?", (suite_id,))
        database.executemany(
            "INSERT INTO suite_cases(suite_id, test_case_id, position) VALUES (?, ?, ?)",
            ((suite_id, case_id, position) for position, case_id in enumerate(members)),
        )
