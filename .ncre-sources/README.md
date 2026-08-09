# NCRE二级MS Office真题数据稿 — 最终报告

套卷：2016年3月真题（无纸化试卷1 / 真题第1套），120分钟，总分100（选择题20 + Word30 + Excel30 + PPT20）。

## 一、文件清单

- exam_dataset.json —— 主数据稿：meta、sources、material_files、choice(20题)、word_task、excel_task、ppt_task、rubric(word/excel/ppt)
- materials/word_source.md —— 邀请函素材全文（7段）
- materials/ppt_source.md —— 图书策划方案素材全文（7个H1节，含H2/H3层级与流程步骤）
- materials/订单明细.csv —— Excel缩减数据集（23行订单）
- materials/编号对照.csv —— 图书编号/名称/单价对照（8种）
- materials/通讯录.csv —— 收件人名单（5人，列：姓名、称谓）
- materials/source_notes.md —— 素材情况、重建数据标注、渠道记录、rubric口径调整说明

## 二、完整度

- 选择题：20/20题完整（题干+4选项+答案+解析）；q03选项经第三方聚合页补全。
- Word题：题干背景+7步结果导向操作+素材全文+rubric 9项（3+3+3+3+4+3+3+3+5=30）。
- Excel题：题干背景+操作步骤+缩减数据集+期望值（脚本复算）+rubric 9项（3+3+5+5+4+3+3+2+2=30）。
- PPT题：题干背景+7页结构+素材全文+放映方案+表格/SmartArt要求+rubric 8项（1+4+4+2+2+4+2+1=20）。
- rubric全部为结果导向、可用 python-docx / openpyxl / python-pptx / zipfile+lxml 客观验证。

## 三、rubric口径调整（已在JSON中标注）

- w3：背景图片未抓到，降级为页面背景填充色 #FDE9D9（检查 w:background）。
- w9：邮件合并改为Python生成等价合并结果文档，仅验证产物属性（页数、每页姓名、模板无姓名）。
- e6期望值按缩减数据集重算：B3=11925、B4=2385、B5=1140、B6=252.25。

## 四、缺口清单

1. 原始素材文件未获取：背景图片.jpg、Word-邀请函参考样式.docx、通讯录.xlsx原始名单、Excel原始634行订单数据、PPT素材docx原文件。均已按上文降级/重建方案处理，不影响评分可执行性。
2. gitcode题库仓库（Universal-Tool/a21a9）访问受阻（403/需凭据），后续如需批量套卷可另行获取授权。
3. ppt素材 PowerPoint 2010创新的功能体验 一节仅存6个H2标题（原文正文截断）；评分只依赖标题与结构。
4. PPT销量统计页的表格数值原卷未给出具体期望值，rubric仅校验表格行列数与列标题。

## 五、下游任务（#4/#6/#7）提示

- 平台seed与题库套件直接消费 exam_dataset.json；material_files 字段给出相对路径映射。
- Excel题考试端需从 订单明细.csv / 编号对照.csv 生成 Excel.xlsx（三工作表：订单明细表/编号对照/统计报告，布局见 excel_task.source_materials）。
- Word题考试端需从 word_source.md + 通讯录.csv 生成 Word.docx 模板；考生交付 Word.docx + Word-邀请函.docx。
