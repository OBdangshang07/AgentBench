import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Button, Modal } from "../components/ui";
import { useMediaQuery, useResponsiveLayout } from "../lib/useResponsiveLayout";

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

describe("responsive panel preferences", () => {
  it("closes panels on a breakpoint change, restores desktop preferences and keeps mobile toggles temporary", () => {
    const { result, rerender } = renderHook(({ narrow }) => useResponsiveLayout(
      () => ({ left: true, right: false, width: 280 }), "responsive-test", narrow ? "narrow" : "wide", narrow ? { left: false, right: false } : {},
    ), { initialProps: { narrow: false } });
    expect(result.current[0]).toEqual({ left: true, right: false, width: 280 });
    rerender({ narrow: true });
    expect(result.current[0].left).toBe(false);
    act(() => result.current[1](current => ({ ...current, right: true })));
    expect(result.current[0].right).toBe(true);
    expect(JSON.parse(localStorage.getItem("responsive-test")!)).toEqual({ left: true, right: false, width: 280 });
    rerender({ narrow: false });
    expect(result.current[0]).toEqual({ left: true, right: false, width: 280 });
    rerender({ narrow: true });
    expect(result.current[0].right).toBe(false);
  });

  it("observes live media changes and removes its listener on unmount", () => {
    let matches = false;
    const listeners = new Set<() => void>();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ get matches() { return matches; }, addEventListener: (_: string, fn: () => void) => listeners.add(fn), removeEventListener: (_: string, fn: () => void) => listeners.delete(fn) })));
    const { result, unmount } = renderHook(() => useMediaQuery("(max-width: 900px)"));
    expect(result.current).toBe(false);
    act(() => { matches = true; listeners.forEach(fn => fn()); });
    expect(result.current).toBe(true);
    unmount();
    expect(listeners.size).toBe(0);
  });
});

function DialogExample() {
  const [open, setOpen] = useState(false);
  const [nested, setNested] = useState(false);
  return <><button onClick={() => setOpen(true)}>打开设置</button>{open && <Modal title="运行设置" description="本地参数" onClose={() => setOpen(false)}>
    <input aria-label="名称" /><button onClick={() => setNested(true)}>打开子弹窗</button><button>保存</button>
    {nested && <Modal title="确认操作" onClose={() => setNested(false)}><button>确认</button></Modal>}
  </Modal>}</>;
}

describe("dialog and action keyboard behavior", () => {
  it("labels the dialog, contains focus, closes with Escape and returns to the opener", () => {
    render(<DialogExample />);
    const opener = screen.getByRole("button", { name: "打开设置" }); opener.focus(); fireEvent.click(opener);
    expect(screen.getByRole("dialog", { name: "运行设置" })).toHaveAccessibleDescription("本地参数");
    expect(opener).toHaveAttribute("inert");
    screen.getByRole("button", { name: "保存" }).focus(); fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(screen.getByRole("button", { name: "关闭" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "保存" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus(); expect(opener).not.toHaveAttribute("inert");
  });

  it("dismisses only the top dialog and restores focus to the parent dialog", () => {
    render(<DialogExample />);
    const opener = screen.getByRole("button", { name: "打开设置" }); opener.focus(); fireEvent.click(opener);
    const nestedOpener = screen.getByRole("button", { name: "打开子弹窗" }); nestedOpener.focus(); fireEvent.click(nestedOpener);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "确认操作" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "运行设置" })).toBeVisible();
    expect(nestedOpener).toHaveFocus(); expect(opener).toHaveAttribute("inert");
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(opener).toHaveFocus(); expect(opener).not.toHaveAttribute("inert");
  });

  it("blocks repeated submissions even when disabled=false is supplied with busy", () => {
    const onClick = vi.fn();
    render(<Button busy disabled={false} className="custom" onClick={onClick}>保存</Button>);
    const button = screen.getByRole("button", { name: "保存" });
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(button).toHaveClass("button", "button-primary", "custom");
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});
