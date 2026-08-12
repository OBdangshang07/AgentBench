import { AlertTriangle, CheckCircle2, Info, RotateCcw, X, XCircle } from "lucide-react";
import {
  Component,
  createContext,
  type ErrorInfo,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type ToastKind = "success" | "error" | "warning" | "info";

interface ToastInput {
  title: string;
  message?: string;
  kind?: ToastKind;
  duration?: number;
  actionLabel?: string;
  onAction?: () => void | Promise<void>;
}

interface ToastRecord extends ToastInput {
  id: number;
  kind: ToastKind;
}

export interface WorkspaceNotification {
  id: number;
  title: string;
  message?: string;
  kind: ToastKind;
  created_at: string;
  read: boolean;
}

export type WorkspaceDensity = "comfortable" | "compact";

interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  detail?: string;
}

interface WorkspaceUxValue {
  notify: (toast: ToastInput) => number;
  dismiss: (id: number) => void;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  notifications: WorkspaceNotification[];
  unreadCount: number;
  markNotificationsRead: () => void;
  clearNotifications: () => void;
  density: WorkspaceDensity;
  setDensity: (density: WorkspaceDensity) => void;
  selectedProjectId: string;
  setSelectedProjectId: (projectId: string) => void;
}

const notificationStorageKey = "agentbench.workspace.notifications.v1";
const densityStorageKey = "agentbench.workspace.density.v1";
const projectStorageKey = "agentbench.workspace.project.v1";

function storedNotifications(): WorkspaceNotification[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(notificationStorageKey) ?? "[]") as WorkspaceNotification[];
    return Array.isArray(value) ? value.slice(-80) : [];
  } catch {
    return [];
  }
}

function storedDensity(): WorkspaceDensity {
  try {
    return window.localStorage.getItem(densityStorageKey) === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable";
  }
}

function storedProjectId() {
  try {
    return window.localStorage.getItem(projectStorageKey) ?? "";
  } catch {
    return "";
  }
}

const WorkspaceUxContext = createContext<WorkspaceUxValue | null>(null);
const safeFallbackUx: WorkspaceUxValue = {
  notify: () => 0,
  dismiss: () => undefined,
  confirm: async () => false,
  notifications: [],
  unreadCount: 0,
  markNotificationsRead: () => undefined,
  clearNotifications: () => undefined,
  density: "comfortable",
  setDensity: () => undefined,
  selectedProjectId: "",
  setSelectedProjectId: () => undefined,
};

export function useWorkspaceUx(): WorkspaceUxValue {
  return useContext(WorkspaceUxContext) ?? safeFallbackUx;
}

const toastIcons = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

export function WorkspaceUxProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const [notifications, setNotifications] = useState<WorkspaceNotification[]>(storedNotifications);
  const [density, setDensityState] = useState<WorkspaceDensity>(storedDensity);
  const [selectedProjectId, setSelectedProjectIdState] = useState(storedProjectId);
  const [confirmState, setConfirmState] = useState<(ConfirmOptions & { resolve: (value: boolean) => void }) | null>(null);
  const toastSequence = useRef(Date.now());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback((input: ToastInput) => {
    const id = ++toastSequence.current;
    const record: ToastRecord = { ...input, id, kind: input.kind ?? "info" };
    setToasts((current) => [...current.slice(-3), record]);
    setNotifications((current) => [...current.slice(-79), {
      id,
      title: record.title,
      message: record.message,
      kind: record.kind,
      created_at: new Date().toISOString(),
      read: false,
    }]);
    if (input.duration !== 0) {
      window.setTimeout(() => dismiss(id), input.duration ?? (record.kind === "error" ? 6500 : 4200));
    }
    return id;
  }, [dismiss]);

  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>((resolve) => {
    setConfirmState({ ...options, resolve });
  }), []);

  const markNotificationsRead = useCallback(() => {
    setNotifications((current) => current.map((notification) => notification.read ? notification : { ...notification, read: true }));
  }, []);

  const clearNotifications = useCallback(() => setNotifications([]), []);

  const setDensity = useCallback((value: WorkspaceDensity) => setDensityState(value), []);
  const setSelectedProjectId = useCallback((value: string) => setSelectedProjectIdState(value), []);

  useEffect(() => {
    try {
      window.localStorage.setItem(notificationStorageKey, JSON.stringify(notifications));
    } catch {
      // Notifications remain available for the current window when storage is unavailable.
    }
  }, [notifications]);

  useEffect(() => {
    document.documentElement.dataset.agentbenchDensity = density;
    try { window.localStorage.setItem(densityStorageKey, density); } catch { /* optional UI preference */ }
  }, [density]);

  useEffect(() => {
    try {
      if (selectedProjectId) window.localStorage.setItem(projectStorageKey, selectedProjectId);
      else window.localStorage.removeItem(projectStorageKey);
    } catch {
      // Project context remains valid until the current window closes.
    }
  }, [selectedProjectId]);

  const unreadCount = useMemo(() => notifications.filter((notification) => !notification.read).length, [notifications]);
  const value = useMemo(() => ({
    notify,
    dismiss,
    confirm,
    notifications,
    unreadCount,
    markNotificationsRead,
    clearNotifications,
    density,
    setDensity,
    selectedProjectId,
    setSelectedProjectId,
  }), [clearNotifications, confirm, density, dismiss, markNotificationsRead, notifications, notify, selectedProjectId, setDensity, setSelectedProjectId, unreadCount]);

  function settleConfirm(approved: boolean) {
    const current = confirmState;
    if (!current) return;
    setConfirmState(null);
    current.resolve(approved);
  }

  return (
    <WorkspaceUxContext.Provider value={value}>
      {children}
      <div className="v5-toast-region" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => {
          const Icon = toastIcons[toast.kind];
          return (
            <section className={`v5-toast ${toast.kind}`} key={toast.id} role={toast.kind === "error" ? "alert" : "status"}>
              <Icon size={18} />
              <div><strong>{toast.title}</strong>{toast.message && <p>{toast.message}</p>}</div>
              {toast.onAction && <button className="action" type="button" onClick={() => { void toast.onAction?.(); dismiss(toast.id); }}><RotateCcw size={13} />{toast.actionLabel ?? "撤销"}</button>}
              <button className="close" type="button" aria-label="关闭通知" onClick={() => dismiss(toast.id)}><X size={15} /></button>
            </section>
          );
        })}
      </div>
      {confirmState && (
        <div className="v4-modal-backdrop v5-confirm-backdrop" role="presentation" onMouseDown={() => settleConfirm(false)}>
          <section className="v5-confirm" role="alertdialog" aria-modal="true" aria-labelledby="v5-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
            <header><span className={confirmState.tone === "danger" ? "danger" : "default"}><AlertTriangle size={19} /></span><div><strong id="v5-confirm-title">{confirmState.title}</strong><p>{confirmState.message}</p></div></header>
            {confirmState.detail && <code>{confirmState.detail}</code>}
            <footer><button className="v4-button secondary" type="button" autoFocus onClick={() => settleConfirm(false)}>{confirmState.cancelLabel ?? "取消"}</button><button className={`v4-button ${confirmState.tone === "danger" ? "danger" : "primary"}`} type="button" onClick={() => settleConfirm(true)}>{confirmState.confirmLabel ?? "确认"}</button></footer>
          </section>
        </div>
      )}
    </WorkspaceUxContext.Provider>
  );
}

interface AppErrorBoundaryState {
  error: Error | null;
}

export class AppErrorBoundary extends Component<{ children: ReactNode }, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("AgentBench workspace render failure", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="v5-fatal-error">
        <span><AlertTriangle size={26} /></span>
        <small>WORKSPACE RECOVERY</small>
        <h1>这个页面遇到了问题</h1>
        <p>你的本地项目和会话数据没有被删除。可以重新载入界面；如果问题重复出现，再导出诊断日志。</p>
        <code>{this.state.error.message || "未知界面错误"}</code>
        <div><button className="v4-button secondary" type="button" onClick={() => this.setState({ error: null })}>返回界面</button><button className="v4-button primary" type="button" onClick={() => window.location.reload()}>重新载入</button></div>
      </main>
    );
  }
}
