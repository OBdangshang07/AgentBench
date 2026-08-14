import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ModelsAndAgents from "../pages/ModelsAndAgents";

const runner = {
  id: "codex-runner",
  name: "Codex CLI",
  runner_type: "codex_cli",
  executable: "codex",
  args: [],
  env: {},
  tools: ["native-cli"],
  limits: {},
  model_override_supported: true,
  enabled: true,
  builtin: true,
  capability: { installed: true, version: "codex-cli 1.0" },
  install: { supported: true, available: true, manager: "npm", source: "npm", command: "npm install -g @openai/codex" },
};

describe("model discovery picker", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads Codex models and keeps the selected Provider route", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      let value: unknown = [];
      if (url.endsWith("/health")) {
        value = { name: "AgentBench Desktop", version: "5.2.3" };
      } else if (url.endsWith("/models/discover")) {
        value = {
          source: "codex-cli",
          source_label: "Codex CLI",
          capability: { installed: true, version: "codex-cli 1.0" },
          providers: [
            { id: "openai_http", label: "OpenAI Login", is_default: true, model_count: 2 },
          ],
          models: [
            { id: "gpt-5.6-sol", label: "GPT-5.6-Sol", provider_id: "openai_http", provider_label: "OpenAI Login", source: "Codex 本机缓存", configured: true, is_default: true },
            { id: "gpt-5.6-terra", label: "GPT-5.6-Terra", provider_id: "openai_http", provider_label: "OpenAI Login", source: "Codex 本机缓存", configured: false, is_default: true },
          ],
          warnings: [],
        };
      } else if (url.endsWith("/runners")) {
        value = [runner];
      }
      return { ok: true, status: 200, json: async () => value } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ModelsAndAgents />);
    fireEvent.click(screen.getByRole("button", { name: /Agent 运行时/ }));
    await screen.findByText("Codex CLI");
    fireEvent.click(screen.getByRole("button", { name: "升级 CLI" }));
    expect(screen.getByText("npm install -g @openai/codex")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    fireEvent.click(screen.getByRole("button", { name: /模型目录/ }));
    fireEvent.click(screen.getByRole("button", { name: "添加模型" }));

    await screen.findByRole("option", { name: /GPT-5.6-Sol/ });
    const modelSelect = screen.getByRole("combobox", { name: /^模型/ });
    fireEvent.change(modelSelect, {
      target: { value: JSON.stringify(["openai_http", "gpt-5.6-terra"]) },
    });

    expect(screen.getByDisplayValue("GPT-5.6-Terra via Codex CLI")).toBeInTheDocument();
    expect(screen.getByText(/执行路由：OpenAI Login/)).toBeInTheDocument();
  });
});
