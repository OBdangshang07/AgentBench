from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

SOURCE_REPOSITORY = "https://github.com/Xnmk029/Xnmk_Library"
SOURCE_COMMIT = "2b03bc0f39f4a1e912816d5a8f752f6d1fd985eb"
SUITE_REVISION = "2026.08-r1"
RUBRIC_VERSION = "1.0"
ASSET_ROOT = Path(__file__).resolve().parent / "frontend_suite_assets"
PROMPT_ROOT = ASSET_ROOT / "prompts"
LICENSE_PATH = ASSET_ROOT / "LICENSE"

# Difficulty is deliberately reclassified on AgentBench's D1-D5/Ultra scale.  The
# source repository level remains provenance only and never drives score weighting.
PROJECTS: tuple[dict[str, Any], ...] = (
    {"key": "svg", "title": "纯 SVG《蒙娜丽莎》矢量复刻", "path": "L1_Basic/SVG", "source_level": "L1", "group": "ui", "difficulty": 4, "minutes": 75, "kind": "visual", "entry": "artwork.svg"},
    {"key": "2048", "title": "2048 × Roguelike 网页游戏", "path": "L2_Intermediate/2048", "source_level": "L2", "group": "games", "difficulty": 4, "minutes": 90, "kind": "game"},
    {"key": "amll", "title": "Apple Music 沉浸式动态歌词播放器", "path": "L2_Intermediate/AMLL", "source_level": "L2", "group": "ui", "difficulty": 3, "minutes": 45, "kind": "ui"},
    {"key": "balatro", "title": "小丑牌网页游戏与动效复刻", "path": "L2_Intermediate/Balatro", "source_level": "L2", "group": "games", "difficulty": 4, "minutes": 100, "kind": "game"},
    {"key": "double-wishbone", "title": "双叉臂悬挂运动学演示", "path": "L2_Intermediate/DoubleWishbone", "source_level": "L2", "group": "graphics", "difficulty": 5, "minutes": 100, "kind": "simulation"},
    {"key": "fpslab", "title": "多游戏适应 FPS 瞄准训练", "path": "L2_Intermediate/FPSlab", "source_level": "L2", "group": "games", "difficulty": 3, "minutes": 50, "kind": "game"},
    {"key": "frontend-showcase", "title": "赛博朋克复合职业前端展台", "path": "L2_Intermediate/FrontendShowcase", "source_level": "L2", "group": "ui", "difficulty": 3, "minutes": 55, "kind": "ui"},
    {"key": "mota", "title": "Flash 风格魔塔 RPG", "path": "L2_Intermediate/MoTa", "source_level": "L2", "group": "games", "difficulty": 3, "minutes": 60, "kind": "game"},
    {"key": "musicgames", "title": "冰与火之舞 × 节奏医生融合音游", "path": "L2_Intermediate/Musicgames", "source_level": "L2", "group": "games", "difficulty": 4, "minutes": 75, "kind": "game"},
    {"key": "penrose-stairs", "title": "交互式 3D 彭罗斯阶梯", "path": "L2_Intermediate/PenroseStairs", "source_level": "L2", "group": "graphics", "difficulty": 4, "minutes": 65, "kind": "graphics"},
    {"key": "sokoban", "title": "草地 Shader 与 3D 推箱子", "path": "L2_Intermediate/Sokoban", "source_level": "L2", "group": "games", "difficulty": 5, "minutes": 120, "kind": "game"},
    {"key": "bicycle3d", "title": "参数化 3D 自行车工作室", "path": "L3_Advanced/Bicycle3D", "source_level": "L3", "group": "graphics", "difficulty": 5, "minutes": 150, "kind": "simulation"},
    {"key": "fpv", "title": "FPV 穿越机花飞模拟器", "path": "L3_Advanced/FPV", "source_level": "L3", "group": "graphics", "difficulty": 5, "minutes": 180, "kind": "simulation"},
    {"key": "industrial-digital-twin", "title": "工业数字孪生设备监控", "path": "L3_Advanced/IndustrialDigitalTwin", "source_level": "L3", "group": "graphics", "difficulty": 5, "minutes": 120, "kind": "simulation"},
    {"key": "minecraft", "title": "浏览器 3D 体素沙盒", "path": "L3_Advanced/Minecraft", "source_level": "L3", "group": "games", "difficulty": 4, "minutes": 100, "kind": "game"},
    {"key": "minecraft-voxy", "title": "VOxy Craft 体素渲染引擎", "path": "L3_Advanced/MinecraftVOxy", "source_level": "L3", "group": "expert", "difficulty": 6, "minutes": 300, "kind": "simulation"},
    {"key": "poolrooms3d", "title": "3D Poolrooms 沉浸式模拟器", "path": "L3_Advanced/Poolrooms3D", "source_level": "L3", "group": "graphics", "difficulty": 5, "minutes": 120, "kind": "graphics"},
    {"key": "rtx", "title": "路径追踪 GPU Benchmark", "path": "L3_Advanced/RTX", "source_level": "L3", "group": "graphics", "difficulty": 5, "minutes": 150, "kind": "simulation"},
    {"key": "rain-world", "title": "节点物理与 IK 生存游戏", "path": "L3_Advanced/RainWorld", "source_level": "L3", "group": "games", "difficulty": 5, "minutes": 150, "kind": "game"},
    {"key": "usp", "title": "USP Match 低多边形机械动画", "path": "L3_Advanced/USP", "source_level": "L3", "group": "graphics", "difficulty": 4, "minutes": 80, "kind": "graphics"},
    {"key": "cloth", "title": "3D 软体布料物理仿真", "path": "L3_Advanced/cloth", "source_level": "L3", "group": "graphics", "difficulty": 4, "minutes": 90, "kind": "simulation"},
    {"key": "teardown", "title": "Teardown 微体素 PBR Demo", "path": "L3_Advanced/teardown", "source_level": "L3", "group": "graphics", "difficulty": 5, "minutes": 120, "kind": "graphics"},
    {"key": "cfd", "title": "3D SPH 流体仿真与基准", "path": "L4_Expert/CFD", "source_level": "L4", "group": "expert", "difficulty": 6, "minutes": 240, "kind": "simulation"},
    {"key": "engine-sim", "title": "浏览器 V8 发动机与驾驶模拟", "path": "L4_Expert/EngineSIM", "source_level": "L4", "group": "expert", "difficulty": 6, "minutes": 300, "kind": "simulation"},
)

GROUPS = {
    "ui": {"name": "Xnmk 前端 · UI 与视觉交互", "description": "高完成度界面、动效与矢量视觉专项。"},
    "games": {"name": "Xnmk 前端 · 网页游戏与状态系统", "description": "游戏闭环、状态机、输入反馈与玩法实现。"},
    "graphics": {"name": "Xnmk 前端 · 3D / WebGL / Shader", "description": "浏览器图形、程序化建模、物理与交互仿真。"},
    "expert": {"name": "Xnmk 前端 · 专家级浏览器工程", "description": "跨领域、长时程的极高难度浏览器工程。"},
}

SPECIFIC_CHECKS: dict[str, list[str]] = {
    "2048": ["移动与合并规则正确", "Roguelike 强化会实际改变规则", "失败、结算和重开形成闭环"],
    "amll": ["歌词自动滚动与点击定位可用", "逐字高亮与播放时间同步", "动态背景保持流畅"],
    "balatro": ["发牌到商店和下一轮形成闭环", "牌型、倍率与回合目标正确", "卡牌关键动作均有反馈"],
    "double-wishbone": ["刚性杆长度约束稳定", "轮跳与转向联动不发散", "关键运动学数据实时可读"],
    "fpv": ["SO(3) 姿态积分满足题面约束", "PID 与刚体受力构成闭环", "键盘或手柄可实际操控飞行"],
    "minecraft-voxy": ["确定性区块生成与网格优化可验证", "Worker 流式加载和 LOD 可运行", "交互、渲染与性能构成完整纵向切片"],
    "rtx": ["渐进采样与重置正确", "Benchmark 重复统计可复现", "Shader 或上下文错误会明确报告"],
    "rain-world": ["自定义节点约束与地形碰撞稳定", "程序化身体不是刚性矩形替代", "IK 和动作响应可观察"],
    "cfd": ["2500–4000 粒子实时运行", "近邻压力与边界碰撞稳定", "基准与颜色映射提供可读反馈"],
    "engine-sim": ["发动机阶次随 RPM 正确跟踪", "音频无持续削波或参数爆音", "车辆动力学、场景与音频联动"],
}


def _manual_rubric(project: dict[str, Any]) -> dict[str, Any]:
    technical = project["kind"] in {"graphics", "simulation"}
    if technical:
        dimensions = [
            {"key": "technical", "label": "核心技术 / 物理正确性", "max_score": 30, "criteria": "核心图形、物理、几何或音频算法真实实现且结果可信。"},
            {"key": "functionality", "label": "功能闭环", "max_score": 25, "criteria": "题面主要功能可实际操作，不是静态展示或占位。"},
            {"key": "visual", "label": "视觉与表现", "max_score": 20, "criteria": "画面完成度、层次、反馈和题面风格达到可展示水平。"},
            {"key": "performance", "label": "性能与稳定性", "max_score": 15, "criteria": "运行稳定、交互流畅，无持续报错、数值爆炸或明显泄漏。"},
            {"key": "engineering", "label": "工程与交付", "max_score": 10, "criteria": "入口明确、结构清楚、说明完整且符合限制。"},
        ]
    else:
        dimensions = [
            {"key": "functionality", "label": "功能完成度", "max_score": 35, "criteria": "题面主要功能全部可实际使用并形成闭环。"},
            {"key": "interaction", "label": "交互正确性与体验", "max_score": 20, "criteria": "状态转换、输入反馈和边界处理正确自然。"},
            {"key": "visual", "label": "视觉完成度", "max_score": 20, "criteria": "布局、风格、动效和细节达到可展示水平。"},
            {"key": "engineering", "label": "工程质量与稳定性", "max_score": 15, "criteria": "运行稳定、结构合理、无明显控制台错误。"},
            {"key": "specific", "label": "题目特定能力", "max_score": 10, "criteria": "题目最具区分度的专项能力得到真实实现。"},
        ]
    checks = SPECIFIC_CHECKS.get(project["key"], [])
    if not checks:
        checks = ["主要交付物可以独立打开或按 README 启动", "不存在 TODO、静态截图冒充或关键功能占位", "题面明确要求均可在作品中找到"]
    return {
        "mode": "manual",
        "version": RUBRIC_VERSION,
        "dimensions": dimensions,
        "checklist": [{"key": f"check-{index + 1}", "label": label} for index, label in enumerate(checks)],
        "critical_defects": [
            {"key": "cannot_launch", "label": "无法启动或没有可查看交付物"},
            {"key": "static_fake", "label": "以静态截图、嵌图或占位冒充核心交互"},
            {"key": "scope_violation", "label": "修改工作区外文件或包含明显越界产物"},
        ],
    }


def _delivery_contract(project: dict[str, Any]) -> str:
    entry = project.get("entry") or "index.html"
    return (
        "\n\n---\n\n"
        "# AgentBench 5.2.0 统一交付约定\n\n"
        "- 仅在当前 AgentBench 工作区内工作，不读取或修改工作区外的任何项目。\n"
        "- 将全部最终作品直接写入当前工作区；不要再创建以模型名命名的外层目录。\n"
        f"- 首选可识别入口为 `{entry}`；若技术栈必须构建，允许使用 `dist/index.html` 或 `build/index.html`。\n"
        "- 额外提供 `README_AGENTBENCH.md`，写明入口、启动方式、已完成功能、已知限制和第三方资源许可。\n"
        "- 不得读取任何历史参测作品；不得以截图或参考位图冒充题目要求的交互实现。\n"
        "- 完成后自行检查入口和主要交互，并在最终回复中给出简短交付摘要。\n"
    )


def build_frontend_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for project in PROJECTS:
        prompt_path = PROMPT_ROOT / f"{project['key']}.md"
        prompt = prompt_path.read_text(encoding="utf-8")
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        difficulty = int(project["difficulty"])
        cases.append(
            {
                "slug": f"frontend.xnmk-{project['key']}",
                "version": SUITE_REVISION,
                "category": f"frontend-{project['group']}",
                "title": project["title"],
                "description": f"Xnmk_Library {project['source_level']} 题目，按 AgentBench 标准重定位为 {'Ultra' if difficulty >= 6 else f'D{difficulty}'}。",
                "instruction": prompt.rstrip() + _delivery_contract(project),
                "tools": ["filesystem", "search", "shell"],
                "limits": {
                    "max_steps": 500,
                    "max_runtime_seconds": 28_800 if difficulty >= 6 else 14_400,
                    "time_target_seconds": int(project["minutes"]) * 60,
                    "token_budget": 800_000 if difficulty >= 6 else 500_000,
                },
                # This validator never invokes an AI judge.  It deliberately transitions
                # a successful Agent delivery to needs_review until a human submits rubric.
                "validators": [{"type": "manual_rubric", "weight": 100, "config": {"rubric_version": RUBRIC_VERSION}}],
                "rubric": _manual_rubric(project),
                "tags": ["frontend", "xnmk-library", project["group"], "manual-review", f"d{difficulty}"],
                "initial_files": {
                    "AGENTBENCH_TASK_SOURCE.md": (
                        f"# 题目来源\n\n- Repository: {SOURCE_REPOSITORY}\n- Commit: `{SOURCE_COMMIT}`\n"
                        f"- Source path: `{project['path']}/PROJECT_PROMPT.md`\n- Prompt SHA-256: `{prompt_hash}`\n"
                        f"- Suite revision: `{SUITE_REVISION}`\n\n本文件仅记录来源；正式任务已由 AgentBench 传入。\n"
                    )
                },
                "metadata": {
                    "difficulty": difficulty,
                    "estimated_minutes": int(project["minutes"]),
                    "capability": "frontend-engineering",
                    "benchmark_generation": "v5.2",
                    "suite_kind": "frontend",
                    "manual_scoring": True,
                    "source_repository": SOURCE_REPOSITORY,
                    "source_commit": SOURCE_COMMIT,
                    "source_path": f"{project['path']}/PROJECT_PROMPT.md",
                    "source_level": project["source_level"],
                    "source_prompt_sha256": prompt_hash,
                    "suite_revision": SUITE_REVISION,
                    "frontend_group": project["group"],
                    "preview_entry": project.get("entry") or "index.html",
                },
            }
        )
    return cases


def project_keys(group: str | None = None) -> list[str]:
    return [item["key"] for item in PROJECTS if group is None or item["group"] == group]
