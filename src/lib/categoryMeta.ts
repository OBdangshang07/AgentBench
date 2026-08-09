import {
  BarChart3,
  Braces,
  BriefcaseBusiness,
  Code2,
  FileSpreadsheet,
  Route,
  Shield,
  Sigma,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface CategoryMeta {
  name: string;
  icon: LucideIcon;
  color: string;
}

export const categoryMeta: Record<string, CategoryMeta> = {
  "instruction-following": { name: "指令遵循", icon: Braces, color: "violet" },
  reasoning: { name: "推理计算", icon: Sigma, color: "blue" },
  "tool-use": { name: "工具使用", icon: Wrench, color: "cyan" },
  "software-engineering": { name: "软件工程", icon: Code2, color: "green" },
  "knowledge-work": { name: "知识工作", icon: BriefcaseBusiness, color: "purple" },
  "data-analysis": { name: "数据分析", icon: BarChart3, color: "orange" },
  "office-exam": { name: "Office 试卷", icon: FileSpreadsheet, color: "emerald" },
  "agentic-workflow": { name: "Agent 工作流", icon: Workflow, color: "teal" },
  security: { name: "安全工程", icon: Shield, color: "red" },
  planning: { name: "规划决策", icon: Route, color: "gold" },
  "ultra-engineering": { name: "Ultra 工程", icon: Code2, color: "ultra" },
  "ultra-planning": { name: "Ultra 规划", icon: Route, color: "ultra" },
};

/** 分类固定顺序（与 categoryMeta 声明顺序一致）。 */
export const categoryOrder = Object.keys(categoryMeta);

/** 不上雷达图的 Ultra 分类。 */
export const ultraCategories = ["ultra-engineering", "ultra-planning"];

/** 可进入雷达图的分类，顺序固定。 */
export const radarCategories = categoryOrder.filter((category) => !ultraCategories.includes(category));

export function categoryName(category: string): string {
  return categoryMeta[category]?.name ?? category;
}
