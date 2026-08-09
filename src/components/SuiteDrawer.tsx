import { useState } from "react";
import { Box, ChevronDown, ListChecks, X } from "lucide-react";
import { useApi } from "../lib/useApi";
import type { SuiteCasePreview } from "../types";
import { ErrorBlock, LoadingBlock } from "./ui";

export function Difficulty({ min = 1, max = 1 }: { min?: number; max?: number }) {
  return <span className={`difficulty-dots ${max >= 6 ? "difficulty-dots-ultra" : ""}`} title={max >= 6 ? "Ultra 难度 6" : `难度 ${min}–${max}`}>{[1, 2, 3, 4, 5, 6].map((level) => <i className={level <= max ? "active" : ""} key={level} />)}</span>;
}

export function SuiteDrawer({ suiteId, suiteName, onClose }: { suiteId: string; suiteName: string; onClose: () => void }) {
  const state = useApi<SuiteCasePreview[]>(`/suites/${suiteId}/cases`);
  const [expandedId, setExpandedId] = useState("");
  return (
    <div className="suite-drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside className="suite-drawer" role="dialog" aria-modal="true" aria-label={`${suiteName} 题目列表`} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <span className="section-kicker">SUITE CASES</span>
            <h2>{suiteName}</h2>
            <p>{state.data ? `共 ${state.data.length} 题 · 点击题目展开完整题面` : "题目清单预览"}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </header>
        {state.loading ? <LoadingBlock label="读取题目列表…" /> : state.error || !state.data ? (
          <ErrorBlock message={state.error ?? "读取题目失败"} retry={() => void state.refresh()} />
        ) : (
          <div className="suite-case-list">
            {state.data.map((item) => {
              const expanded = expandedId === item.id;
              return (
                <div className={`suite-case${expanded ? " expanded" : ""}`} key={item.id}>
                  <button type="button" className="suite-case-heading" onClick={() => setExpandedId(expanded ? "" : item.id)}>
                    <div className="suite-case-title-row">
                      <strong>{item.title}</strong>
                      <ChevronDown size={15} className="suite-case-chevron" />
                    </div>
                    <div className="suite-case-tags">
                      <span className="case-category">{item.category}</span>
                      <Difficulty max={item.difficulty ?? 1} />
                      {Boolean(item.estimated_minutes) && <span className="case-fact">约 {item.estimated_minutes} 分钟</span>}
                      {item.requires_docker && <span className="case-docker"><Box size={11} /> 需 Docker</span>}
                    </div>
                    <p>{item.description}</p>
                  </button>
                  {expanded && <div className="suite-case-instruction"><span>完整题面</span><pre>{item.instruction}</pre></div>}
                </div>
              );
            })}
            {!state.data.length && <div className="inline-empty"><ListChecks size={24} /><p>该套件暂无题目</p></div>}
          </div>
        )}
      </aside>
    </div>
  );
}
