import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef } from "react";
import type { Terminal as XTerm } from "@xterm/xterm";

export function TerminalView({
  content,
  onData,
  onResize,
}: {
  content: string;
  onData?: (data: string) => void;
  onResize?: (columns: number, rows: number) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<XTerm | null>(null);
  const writtenRef = useRef(0);
  const contentRef = useRef(content);
  const onDataRef = useRef(onData);
  const onResizeRef = useRef(onResize);
  contentRef.current = content;
  onDataRef.current = onData;
  onResizeRef.current = onResize;

  useEffect(() => {
    if (!hostRef.current) return;
    let disposed = false;
    let observer: ResizeObserver | null = null;
    void Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]).then(
      ([xterm, addon]) => {
        if (disposed || !hostRef.current) return;
        const terminal = new xterm.Terminal({
          convertEol: false,
          cursorBlink: true,
          disableStdin: !onDataRef.current,
          fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
          fontSize: 12,
          lineHeight: 1.25,
          scrollback: 5000,
          theme: {
            background: "#05090e",
            foreground: "#c9d8d5",
            cursor: "#42d6b0",
            selectionBackground: "#6d61d855",
            black: "#0a0e14",
            green: "#42d6b0",
            cyan: "#58c8ed",
            yellow: "#f5b94c",
            red: "#ef6b79",
            magenta: "#a89dff",
            white: "#dce3ee",
          },
        });
      const fit = new addon.FitAddon();
      terminal.loadAddon(fit);
      terminal.open(hostRef.current);
      terminal.onData((data) => onDataRef.current?.(data));
      terminalRef.current = terminal;
      if (contentRef.current) terminal.write(contentRef.current);
      writtenRef.current = contentRef.current.length;
      const fitTerminal = () => {
        fit.fit();
        if (terminal.cols >= 40 && terminal.rows >= 10) onResizeRef.current?.(terminal.cols, terminal.rows);
      };
      window.setTimeout(fitTerminal, 0);
      observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fitTerminal);
      observer?.observe(hostRef.current);
      },
    );
    return () => {
      disposed = true;
      observer?.disconnect();
      terminalRef.current?.dispose();
      terminalRef.current = null;
      writtenRef.current = 0;
    };
  }, []); // callbacks use refs; content updates are handled by the incremental writer below.

  useEffect(() => {
    const terminal = terminalRef.current;
    if (!terminal) return;
    if (content.length < writtenRef.current) {
      terminal.reset();
      writtenRef.current = 0;
    }
    const delta = content.slice(writtenRef.current);
    if (delta) terminal.write(delta);
    writtenRef.current = content.length;
  }, [content]);

  return <div className="v4-xterm" ref={hostRef} />;
}
