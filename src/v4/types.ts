export type PermissionProfile = "readonly" | "workspace" | "standard" | "full";
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max";

export interface SessionAttachment {
  id: string;
  kind: "attachment";
  name: string;
  size: number;
  media_type: string;
  created_at: string;
}

export interface StudioDashboardData {
  project_count: number;
  session_count: number;
  active_sessions: number;
  pending_approvals: number;
  completed_tasks: number;
  open_tasks: number;
  total_tokens: number;
  total_cost: number;
  active_sessions_list: AgentSession[];
  pending_approvals_list: ApprovalRequest[];
  recent_projects: Project[];
  recent_failures: Array<{
    id: string;
    title: string;
    status: string;
    updated_at: string;
    project_name: string;
    runner_name: string | null;
    model_name: string | null;
    error_message: string | null;
  }>;
  runtime_health: {
    models_enabled: number;
    runners_enabled: number;
    mcp_enabled: number;
    mcp_healthy: number;
    mcp_error: number;
  };
}

export interface WorkspaceSearchResult {
  id: string;
  kind: "project" | "session" | "task" | "flow";
  title: string;
  subtitle: string;
  extra: string | null;
  status: string | null;
  path: string;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  default_runner_id: string | null;
  default_model_id: string | null;
  permission_profile: PermissionProfile;
  pinned: boolean;
  archived: boolean;
  root_path: string;
  branch: string | null;
  session_count: number;
  active_sessions: number;
  pending_approvals: number;
  created_at: string;
  updated_at: string;
  last_opened_at: string | null;
  roots?: Array<{ id: string; root_path: string; label: string; access_mode: PermissionProfile; is_primary: boolean; created_at: string }>;
}

export interface ProjectHealth {
  project_id: string;
  ready: boolean;
  checks: Array<{ id: string; label: string; ok: boolean; detail: string }>;
  checked_at: string;
}

export interface ProjectTreeEntry {
  name: string;
  path: string;
  kind: "file" | "directory";
  size: number;
  modified_ns: number;
}

export interface ProjectTree {
  project_id: string;
  root_path: string;
  path: string;
  entries: ProjectTreeEntry[];
}

export interface ProjectFileSearch {
  project_id: string;
  root_path: string;
  query: string;
  entries: ProjectTreeEntry[];
  scanned: number;
  truncated: boolean;
}

export interface StudioMessage {
  id: string;
  turn_id: string | null;
  role: "user" | "assistant" | "system";
  content: string;
  metadata: { context?: Array<Record<string, unknown>> };
  created_at: string;
}

export interface StudioEvent {
  id: number;
  session_id: string;
  turn_id: string | null;
  seq: number;
  event_type: string;
  visibility: "user" | "recording_safe";
  payload: Record<string, unknown>;
  created_at: string;
}

export interface StudioTurn {
  id: string;
  session_id: string;
  turn_no: number;
  status: string;
  user_message: string;
  final_answer: string | null;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  duration_ms: number;
  steps: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface FileChange {
  id: string;
  turn_id: string | null;
  path: string;
  change_type: "created" | "modified" | "deleted";
  before_sha256: string | null;
  after_sha256: string | null;
  size_delta: number;
  status: string;
  created_at: string;
}

export interface ApprovalRequest {
  id: string;
  session_id: string;
  turn_id: string | null;
  request_type: string;
  status: "pending" | "approved" | "denied";
  title: string;
  description: string;
  risk_level: string;
  request: Record<string, unknown>;
  decision: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
}

export interface AgentSession {
  id: string;
  project_id: string;
  project_name: string;
  title: string;
  runner_id: string;
  runner_name: string;
  runner_type: string;
  model_id: string;
  model_name: string;
  status: string;
  permission_profile: PermissionProfile;
  reasoning_effort: ReasoningEffort;
  skill_pack_id: string | null;
  skill_pack_name: string | null;
  native_session_id: string | null;
  workspace_path: string;
  summary: string;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  duration_ms: number;
  turn_count: number;
  pending_approvals: number;
  archived: boolean;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentSessionDetail extends AgentSession {
  messages: StudioMessage[];
  message_count: number;
  messages_truncated: boolean;
  events: StudioEvent[];
  approvals: ApprovalRequest[];
  turns: StudioTurn[];
  file_changes: FileChange[];
  artifacts: Array<Record<string, unknown>>;
}

export interface StudioTask {
  id: string;
  project_id: string | null;
  project_name: string | null;
  title: string;
  description: string;
  status: "backlog" | "queued" | "running" | "approval" | "completed" | "failed" | "cancelled";
  priority: "low" | "normal" | "high" | "urgent";
  runner_id: string | null;
  runner_name: string | null;
  model_id: string | null;
  model_name: string | null;
  session_id: string | null;
  due_at: string | null;
  tags: string[];
  depends_on: string[];
  result_summary: string;
  retry_of: string | null;
  archived: boolean;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentFlowSummary {
  id: string;
  project_id: string | null;
  project_name: string | null;
  name: string;
  description: string;
  status: string;
  node_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgentFlow extends AgentFlowSummary {
  settings: {
    max_retries?: number;
    max_concurrency?: number;
    max_runtime_seconds?: number;
    max_cost_usd?: number;
    max_tokens?: number;
  };
  nodes: Array<{
    id: string;
    node_type: string;
    name: string;
    position_x: number;
    position_y: number;
    config: Record<string, unknown>;
    status: string;
    attempts: number;
    error_message: string | null;
    output: Record<string, unknown>;
    session_id: string | null;
  }>;
  edges: Array<{
    id: string;
    source_node_id: string;
    target_node_id: string;
    edge_type: string;
    condition: Record<string, unknown>;
  }>;
}

export interface FlowValidationIssue {
  code: string;
  message: string;
  node_id?: string;
}

export interface FlowValidation {
  valid: boolean;
  errors: FlowValidationIssue[];
  warnings: FlowValidationIssue[];
  roots: string[];
  topological_order: string[];
  levels: string[][];
  node_count: number;
  edge_count: number;
}

export interface AgentFlowVersion {
  id: string;
  graph_id: string;
  version_no: number;
  label: string;
  name: string;
  description: string;
  settings: Record<string, unknown>;
  definition: Record<string, unknown>;
  created_at: string;
}

export interface AgentFlowRun {
  id: string;
  graph_id: string;
  version_no: number | null;
  status: string;
  dry_run: boolean;
  retry_node_id: string | null;
  error_message: string;
  result: Record<string, unknown>;
  usage: {
    cost_usd?: number;
    tokens_input?: number;
    tokens_output?: number;
    duration_ms?: number;
  };
  started_at: string;
  completed_at: string | null;
  created_at: string;
}

export interface McpServer {
  id: string;
  name: string;
  transport: "stdio" | "sse" | "streamable_http";
  command: string | null;
  args: string[];
  url: string | null;
  env_keys: string[];
  tools: Array<{ name: string; description?: string; inputSchema?: Record<string, unknown> }>;
  health_status: "unknown" | "online" | "offline";
  last_error: string | null;
  last_checked_at: string | null;
  enabled: boolean;
  builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkillPack {
  id: string;
  name: string;
  description: string;
  content: string;
  tools: string[];
  permission_profile: PermissionProfile | null;
  builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface ToolGatewayStatus {
  id: "filesystem" | "git-workspace" | "browser" | "terminal";
  name: string;
  status: "online" | "offline" | "approval" | "unavailable";
  detail: string;
}

export interface BrowserPage {
  id: string;
  title: string;
  url: string;
  type?: string;
}

export interface BrowserStatus {
  installed: boolean;
  running: boolean;
  executable: string | null;
  engine: string | null;
  profile_path: string;
  page_count: number;
  pages: BrowserPage[];
  manual_takeover: boolean;
}

export interface BrowserSnapshot {
  title: string;
  url: string;
  text: string;
  links: Array<{ index: number; text: string; href: string; selector?: string }>;
  controls: Array<{ index: number; tag: string; type: string | null; text: string; id: string | null; name: string | null; value?: string | null; disabled?: boolean; selector?: string }>;
}
