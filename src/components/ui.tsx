import type { ButtonHTMLAttributes, ComponentProps, PropsWithChildren, ReactNode } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import { statusLabel, statusTone } from "../lib/format";

export function Button({
  children,
  variant = "primary",
  busy,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  busy?: boolean;
}) {
  return (
    <button className={`button button-${variant}`} disabled={busy || props.disabled} {...props}>
      {busy && <LoaderCircle size={16} className="spin" />}
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
  ...props
}: ComponentProps<"section">) {
  return <section className={`card ${className}`} {...props}>{children}</section>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status status-${statusTone(status)}`}>{statusLabel[status] ?? status}</span>;
}

export function Score({ value, large = false }: { value?: number | null; large?: boolean }) {
  if (value == null) return <span className="score-empty">—</span>;
  const tone = value >= 85 ? "great" : value >= 60 ? "good" : "low";
  return <span className={`score score-${tone} ${large ? "score-large" : ""}`}>{value.toFixed(1)}</span>;
}

export function LoadingBlock({ label = "读取本地数据…" }: { label?: string }) {
  return (
    <div className="state-block">
      <LoaderCircle className="spin" size={24} />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBlock({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="state-block state-error">
      <AlertTriangle size={24} />
      <div>
        <strong>本地服务暂时不可用</strong>
        <p>{message}</p>
      </div>
      {retry && (
        <Button variant="secondary" onClick={retry}>
          重试
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <div className="empty-orbit" />
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

export function Field({ label, hint, children }: PropsWithChildren<{ label: string; hint?: string }>) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function Modal({
  title,
  description,
  children,
  onClose,
}: PropsWithChildren<{ title: string; description?: string; onClose: () => void }>) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h2>{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
