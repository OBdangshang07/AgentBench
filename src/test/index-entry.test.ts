import { describe, expect, it } from "vitest";
import html from "../../index.html?raw";

describe("desktop HTML entry", () => {
  it("mounts the React application instead of a generated visual artifact", () => {
    expect(html).toContain('<div id="root"></div>');
    expect(html).toContain('<script type="module" src="/src/main.tsx"></script>');
    expect(html).not.toContain("data-hf-id");
    expect(html).not.toContain("PROVISIONAL LEADERBOARD");
  });
});
