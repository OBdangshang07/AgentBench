import { describe, expect, it } from "vitest";
import { gradeOf } from "../lib/grades";
import { RADAR_CENTER, RADAR_RADIUS, radarPoint } from "../components/RadarChart";

describe("gradeOf rating mapping", () => {
  it("maps score bands to S/A/B/C/D", () => {
    expect(gradeOf(100)).toBe("S");
    expect(gradeOf(90)).toBe("S");
    expect(gradeOf(89.9)).toBe("A");
    expect(gradeOf(80)).toBe("A");
    expect(gradeOf(79)).toBe("B");
    expect(gradeOf(70)).toBe("B");
    expect(gradeOf(69)).toBe("C");
    expect(gradeOf(60)).toBe("C");
    expect(gradeOf(59.9)).toBe("D");
    expect(gradeOf(0)).toBe("D");
  });
});

describe("radarPoint vertex geometry", () => {
  it("points the first axis straight up at full radius", () => {
    const point = radarPoint(0, 4, 1);
    expect(point.x).toBeCloseTo(RADAR_CENTER, 6);
    expect(point.y).toBeCloseTo(RADAR_CENTER - RADAR_RADIUS, 6);
  });

  it("scales points linearly with the score ratio", () => {
    const half = radarPoint(2, 4, 0.5);
    const full = radarPoint(2, 4, 1);
    expect(half.x).toBeCloseTo(RADAR_CENTER + (full.x - RADAR_CENTER) / 2, 6);
    expect(half.y).toBeCloseTo(RADAR_CENTER + (full.y - RADAR_CENTER) / 2, 6);
  });

  it("spaces axes evenly around the circle", () => {
    const right = radarPoint(1, 4, 1);
    expect(right.x).toBeCloseTo(RADAR_CENTER + RADAR_RADIUS, 6);
    expect(right.y).toBeCloseTo(RADAR_CENTER, 6);
    const down = radarPoint(2, 4, 1);
    expect(down.x).toBeCloseTo(RADAR_CENTER, 6);
    expect(down.y).toBeCloseTo(RADAR_CENTER + RADAR_RADIUS, 6);
  });
});
