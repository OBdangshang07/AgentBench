export type Grade = "S" | "A" | "B" | "C" | "D";

/** 0-100 分数映射为评级：S≥90、A 80-89、B 70-79、C 60-69、D<60。 */
export function gradeOf(score: number): Grade {
  if (score >= 90) return "S";
  if (score >= 80) return "A";
  if (score >= 70) return "B";
  if (score >= 60) return "C";
  return "D";
}

export const gradeDescription: Record<Grade, string> = {
  S: "卓越（≥90）",
  A: "优秀（80-89）",
  B: "良好（70-79）",
  C: "及格（60-69）",
  D: "待提升（<60）",
};
