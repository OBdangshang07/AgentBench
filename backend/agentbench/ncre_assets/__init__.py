"""NCRE 二级 MS Office 真题卷（2016年3月 无纸化试卷1）题库资产。

数据来源见工作区 .ncre-sources/exam_dataset.json 与 materials/（内部研究用途）。
本包包含：
- exam_data: 结构化真题数据（选择题题干、操作题素材内容、期望统计值）。
- build_assets: 一次性素材重建脚本，将文字/CSV 数据重建为 .docx/.xlsx 素材，
  并把 base64 结果写入 blobs.py 供 catalog.py 嵌入 initial_files。
- blobs: 由 build_assets 生成的 base64 素材常量（勿手改）。

注意：选择题答案表只允许出现在 catalog.py 私有判分脚本（private_files）内，
严禁放入 instruction 或 initial_files。
"""
