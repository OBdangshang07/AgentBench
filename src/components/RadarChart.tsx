export interface RadarDatum {
  label: string;
  value: number;
}

export const RADAR_SIZE = 300;
export const RADAR_CENTER = RADAR_SIZE / 2;
export const RADAR_RADIUS = 96;

/** 计算第 index 个轴上、相对满量程 ratio（0-1）位置的坐标。0 号轴指向正上方。 */
export function radarPoint(
  index: number,
  total: number,
  ratio: number,
  radius: number = RADAR_RADIUS,
  center: number = RADAR_CENTER,
): { x: number; y: number } {
  const angle = -Math.PI / 2 + (2 * Math.PI * index) / total;
  return {
    x: center + Math.cos(angle) * radius * ratio,
    y: center + Math.sin(angle) * radius * ratio,
  };
}

function toPoints(coords: Array<{ x: number; y: number }>): string {
  return coords.map(({ x, y }) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

/** 纯 SVG 雷达图：三层同心网格多边形 + 轴线 + 数据多边形 + 顶点圆点 + 外侧标签。 */
export default function RadarChart({ data, ariaLabel }: { data: RadarDatum[]; ariaLabel?: string }) {
  if (!data.length) return null;
  const total = data.length;
  const gridRatios = [1 / 3, 2 / 3, 1];
  const dataPoints = data.map((datum, index) =>
    radarPoint(index, total, Math.max(0, Math.min(100, datum.value)) / 100),
  );
  return (
    <svg
      className="radar-chart"
      viewBox={`0 0 ${RADAR_SIZE} ${RADAR_SIZE}`}
      role="img"
      aria-label={ariaLabel ?? "能力雷达图"}
    >
      {gridRatios.map((ratio) => (
        <polygon
          key={ratio}
          className="radar-grid"
          points={toPoints(Array.from({ length: total }, (_, index) => radarPoint(index, total, ratio)))}
        />
      ))}
      {Array.from({ length: total }, (_, index) => {
        const outer = radarPoint(index, total, 1);
        return (
          <line
            key={index}
            className="radar-axis"
            x1={RADAR_CENTER}
            y1={RADAR_CENTER}
            x2={outer.x}
            y2={outer.y}
          />
        );
      })}
      <polygon className="radar-data" points={toPoints(dataPoints)} />
      {dataPoints.map((point, index) => (
        <circle key={index} className="radar-vertex" cx={point.x} cy={point.y} r={3.2} />
      ))}
      {data.map((datum, index) => {
        const label = radarPoint(index, total, 1.2);
        const cos = Math.cos(-Math.PI / 2 + (2 * Math.PI * index) / total);
        const anchor = Math.abs(cos) < 0.3 ? "middle" : cos > 0 ? "start" : "end";
        return (
          <text key={datum.label} className="radar-label" x={label.x} y={label.y} textAnchor={anchor} dominantBaseline="middle">
            {datum.label}
          </text>
        );
      })}
    </svg>
  );
}
