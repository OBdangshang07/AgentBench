# 素材文件情况与来源说明（2016年3月真题 无纸化试卷1）

## 一、素材抓取情况

| 原卷素材 | 状态 | 处理方式 |
|---|---|---|
| Word.docx（邀请函文稿） | 文字全文已抓到 | 全文落盘 materials/word_source.md（7段） |
| 通讯录.xlsx | 原始文件未抓到 | 以 materials/通讯录.csv 等价重建（列：姓名、称谓，共5人） |
| 背景图片.jpg | 未抓到 | 任务降级为页面背景填充色 #FDE9D9（rubric w3 已标注口径调整） |
| Word-邀请函参考样式.docx | 未抓到 | 格式要求由官方解题步骤还原，直接写入 word_task.steps 第3-5条 |
| Excel.xlsx（订单明细634行+编号对照+统计报告） | 原始数据未抓到 | 构造结构同构缩减数据集：订单明细.csv（23行）+编号对照.csv（8书）；rubric期望值已按缩减数据重算并脚本复算验证 |
| 图书策划方案.docx（PPT素材） | 文字全文已抓到 | 全文落盘 materials/ppt_source.md，两个独立转载源交叉验证 |

## 二、重建/拟定数据标注

- 通讯录.csv：李达志来自公开转载题干；王建国、刘晓梅、陈志强、赵雅琴4人为拟定姓名，仅用于合并结果生成，不影响评分点。
- 订单明细.csv / 编号对照.csv：全部为按原卷表结构构造的缩减数据；期望值 B3=11925、B4=2385、B5=1140、B6=252.25 已经独立脚本复算（VLOOKUP/SUM/SUMPRODUCT口径）。
- 选择题q03的四个选项为补全（原页面选项缺失，经百度文库聚合页同题补齐）。
- ppt_source.md 中 PowerPoint 2010创新的功能体验 一节仅含6个H2标题（原文正文为省略号截断），评分仅依赖标题文本与结构，不受影响。

## 三、来源渠道记录

成功渠道：
- 题干全文+官方解题步骤：https://mip.oh100.com/kaoshi/ncre2/tiku/265282.html
- 选择题20题：http://m.kaoshi.yjbys.com/ncre2/tiku/484467.html
- q03选项补全：https://wk.baidu.com/aggs/0a4df642a8956bec0975e3b0.html
- PPT素材全文：https://m.renrendoc.com/paper/329084520.html 与 https://m.renrendoc.com/paper/245387654.html（交叉验证）
- 邀请函原文：https://easylearn.baidu.com/edu-page/tiangong/questiondetail?fr=search&id=1724317008463950530

失败/受阻渠道：
- gitcode.com/Universal-Tool/a21a9（NCRE题库仓库）：WebFetch返回403/418，git clone需凭据，放弃。
- book118等付费文档：仅预览页确认套卷身份，未采用付费内容。

## 四、rubric口径调整说明（按leader要求）

1. Word邮件合并→结果导向：Agent无GUI且评分走OOXML属性检查，邮件合并域/过程无法客观验证。已改写为用Python从 通讯录.csv 直接生成等价合并结果文档 Word-邀请函.docx（每人一页、仅替换姓名）；rubric w9 只检查可客观验证的产物属性（页数=通讯录人数、每页恰含1位名单姓名、模板文档不含姓名），并在 rubric.word.w9.note 中明确标注口径调整。

2. Excel缩减数据集：原卷634行未抓到，采用23行同构缩减数据；rubric e6 涉及的统计单元格期望值（B3销售额合计=11925、B4 BK-83021 2012年销量=2385、B5 隆华书店2011年Q3销量=1140、B6 隆华2011月均=252.25）与缩减数据严格对应，且经独立Python脚本按订单明细复算验证。
