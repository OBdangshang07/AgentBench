# paper02 / paper03 数据稿补充说明（README_paper02_03.md）

paper01（2016年3月第1套）说明见原 README.md，本文件不改动原文件，仅补充两套新卷。

## 产出文件
- exam_dataset_paper02.json：经典题库第2套（领慧讲堂海报 / 学生成绩单统计 / 水资源利用与节水）
- exam_dataset_paper03.json：经典题库第4套（统计工作年报 / 人口普查数据整合 / 物理课件整合）
- materials/paper02/：word_poster.md（海报文稿）、成绩单.csv（12名学生缩减数据集）、water_ppt_source.md（节水PPT素材）
- materials/paper03/：word_annual_report.md（年报全文）、第五次普查数据.csv、第六次普查数据.csv、咨询情况表.csv、ppt_slides.md（两份物理课件结构）
## 套别与年份口径
- NCRE二级为题库抽卷制（约39-40套固定套卷多年流转复用），市面标注的2021-2024真题多出自同一题库。
- paper02 = 经典题库第2套：2013年起多期无纸化考试流转使用，近年考前辅导资料（wenku.csdn.net、oh100/yjbays等）仍作为高频真题收录。meta.paper_name 已如实标注。
- paper03 = 经典题库第4套：2017年9月起多期真题流转使用，book118《历年计算机二级MS Office真题》合集与wk.baidu.com聚合页均收录。
- 2022年后全新原创套卷在公开渠道无完整免费题面与步骤，故按任务口径采用经典题库套卷并如实标注年份。
## 题材与考点差异（相对paper01）
| 卷 | Word | Excel | PPT |
|----|------|-------|-----|
| paper01 | 邀请函+邮件合并(降级) | 图书销售VLOOKUP/SUMPRODUCT | 图书策划方案 |
| paper02 | 海报排版：自定义纸张27x35cm、背景色、大字号标题、A4横向第2页、日程表格、报名流程列表 | 成绩单：条件格式、SUM/AVERAGE、MID提取班级、分类汇总+标签色、柱状图 | 水资源利用与节水：自建主题、多版式、图片、超链接 |
| paper03 | 长文档排版：16开页面、封面分页、文内表格+饼图、标题样式、超链接+脚注、两栏、目录域、奇偶页眉 | 人口普查：双表导入+表格样式、千分位、合并排序、增长数/比重变化列、统计指标、透视降级扁平汇总 | 物理课件整合：双主题合并9页、仅标题页、对比表格页、内部超链接、编号页脚、切换 |

选择题：paper01/paper02/paper03 三卷各20题，经校验题干零重复。
## 素材缺口清单（原始docx/xlsx/pptx均未抓到，全部以文字/CSV重建）
paper02：
1. 海报背景图与配图Pic1/Pic2 -> 背景降级为纯色填充FFF2CC（rubric w3标注）；配图不评分
2. 讲座日程.xlsx -> 以 word_poster.md 内日程表文字重建为文档内4行3列表格
3. 报名流程SmartArt -> 降级为编号列表，按paper01口径不考SmartArt属性
4. 成绩单原始xls（数百行真实数据） -> 构造结构同构的12名学生缩减数据集（3个班级、7科），期望值已按该集复算
5. 节水PPT图片素材 -> 仅要求>=2张图片（占位图即可），动画/背景音乐不评分
paper03：
1. 年报原文档 -> 依据公开题面与解析全文重建，尾部两节为题面口径结构重建（已在word_annual_report.md注明）
2. 咨询情况表原始图 -> 以咨询情况表.csv重建（4行3列），饼图仅验证百分比标签
3. 第五次普查分省2000年人口 -> 按官方比重反推重建为整数，与官方公报存在个位级舍入误差；全国合计口径为31地区求和（不含现役军人等未分省人口，2000差33058200、2010差6949985），期望值全部按CSV复算
4. 数据透视表要求 -> openpyxl不可客观验证，降级为扁平汇总（rubric e8标注）
5. 两份物理课件pptx -> 按ppt_slides.md结构重建，主题A/B以不同slideMaster验证；动画不评分；PDF另存步骤跳过
## 期望值与复算口径
- 两套卷 excel_task.expected_values 均由独立Python脚本基于 materials 下CSV复算（.tmp/gen_materials.py 与 validate_papers.py），rubric期望值与数据集严格对应。
- paper02：total_K（学号:总分）、avg_L（学号:平均分,两位小数）、class_avg（班级:7科平均列表）。成绩列为CSV第4列起；学号第3-4位为班级码。
- paper03：regions_sorted（31地区Unicode升序）、growth_desc_gt50m（2010人口>5000万的10地区按增长数降序：[地区,2010人口,增长数]）、stats（地区数31、两次普查31地区合计、超5000万地区数10、其2010人口平均76190093.2）。
- 校验结果：两JSON合法、四部分齐全、rubric合计30/30/20、期望值与CSV逐项一致、三卷选择题零重复。
## 来源与可达性
- paper02 选择题与解析：m.yjbys.com 题库页（UTF-8缓存可读）；操作题题面与步骤：wenku.csdn.net 近年真题讲解docx转述、mip.oh100.com 文字版
- paper03 题面与步骤：book118 历年真题合集页、wk.baidu.com 聚合页、renrendoc 转载页；人口普查数据：国家统计局第五/六次普查公报（WebSearch检索核对）
- 已知失败渠道：gitcode.com/Universal-Tool/a21a9（403）；oh100/yjbays 桌面页直接抓取返回GBK乱码需走缓存；未来教育/虎奔等商业软件内容未抓取
- 各卷 sources 字段内记录了每条素材对应的URL与用途。