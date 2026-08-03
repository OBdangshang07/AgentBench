import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Score, StatusBadge } from "../components/ui";

describe("evaluation UI primitives", () => {
  it("renders evidence-facing score and status", () => {
    render(<><Score value={91.25} /><StatusBadge status="completed" /></>);
    expect(screen.getByText("91.3")).toHaveClass("score-great");
    expect(screen.getByText("已完成")).toHaveClass("status-success");
  });
});
