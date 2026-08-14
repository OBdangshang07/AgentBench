export type JsonObject = Record<string, unknown>;
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max";
export type ReasoningPolicy = "standard" | "maximum" | "native" | "custom" | "historical";

export interface ModelConfig {
  id: string;
  name: string;
  provider: string;
  model_name: string;
  base_url?: string;
  api_style: "openai" | "anthropic" | "mock";
  settings: { temperature?: number; max_tokens?: number; agent_provider?: string };
  input_price: number;
  output_price: number;
  enabled: boolean;
  builtin: boolean;
  has_secret: boolean;
}

export type ModelSource =
  | "api"
  | "codex-cli"
  | "claude-code"
  | "opencode-cli"
  | "reasonix-cli"
  | "gemini-cli"
  | "aider-cli"
  | "kimi-code"
  | "qoder-cli"
  | "cursor-cli"
  | "deepseek-harness";

export interface DiscoveredModel {
  id: string;
  label: string;
  provider_id: string;
  provider_label: string;
  source: string;
  configured: boolean;
  is_default: boolean;
}

export interface DiscoveredProvider {
  id: string;
  label: string;
  base_url?: string;
  is_default: boolean;
  model_count: number;
}

export interface ModelDiscoveryResult {
  source: ModelSource;
  source_label: string;
  capability: {
    installed: boolean;
    executable?: string;
    version?: string;
    endpoint?: string;
    error?: string;
    warning?: string;
    install_command?: string;
    installation?: "temporary_npx" | string;
    desktop_installed?: boolean;
    desktop_executable?: string;
    desktop_configured?: boolean;
    config_path?: string;
    note?: string;
  };
  models: DiscoveredModel[];
  providers: DiscoveredProvider[];
  warnings: string[];
}

export interface Runner {
  id: string;
  name: string;
  runner_type:
    | "unified"
    | "codex_cli"
    | "claude_code_cli"
    | "opencode_cli"
    | "reasonix_cli"
    | "gemini_cli"
    | "aider_cli"
    | "kimi_code_cli"
    | "qoder_cli"
    | "cursor_cli"
    | "deepseek_harness"
    | "command";
  executable?: string;
  args: string[];
  env: Record<string, string>;
  tools: string[];
  limits: JsonObject;
  model_override_supported: boolean;
  enabled: boolean;
  builtin: boolean;
  capability: {
    installed: boolean;
    executable?: string;
    version?: string;
    error?: string;
    warning?: string;
    install_command?: string;
    installation?: string;
    desktop_installed?: boolean;
    desktop_executable?: string;
    note?: string;
  };
  install: {
    supported: boolean;
    available: boolean;
    manager?: string;
    source?: string;
    command?: string;
    unavailable_reason?: string | null;
    manual_instructions?: string;
  };
  adapter?: {
    conversation_mode: "native_resume" | "history_replay";
    native_resume: boolean;
    structured_events: "full" | "stream" | "filtered_text";
    mcp: boolean;
    visible_browser?: boolean;
    model_override: boolean;
    approval_gate: boolean;
    process_tree_cancel: boolean;
    interactive_terminal: boolean;
    reasoning_control?: {
      supported: boolean;
      maximum?: string | null;
      verified: boolean;
      note: string;
    };
  };
}

export interface RunnerInstallJob {
  id: string;
  runner_id: string;
  runner_name: string;
  runner_type: Runner["runner_type"];
  status: "queued" | "running" | "completed" | "failed";
  source: string;
  command: string;
  manager: string;
  stdout: string;
  stderr: string;
  exit_code?: number | null;
  duration_ms: number;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface TestCase {
  id: string;
  slug: string;
  version: string;
  category: string;
  title: string;
  description: string;
  builtin: boolean;
  difficulty?: number;
  estimated_minutes?: number;
  capability?: string;
  tags?: string[];
  tools?: string[];
  requires_docker?: boolean;
  requires_judge?: boolean;
  sample_size?: number;
  avg_score?: number | null;
  full_score_rate?: number | null;
  low_discrimination?: boolean;
  manual_scoring?: boolean;
  suite_kind?: string;
  definition?: {
    instruction: string;
    tools: string[];
    validators: Array<{ type: string; weight: number; config: JsonObject }>;
    limits: JsonObject;
    tags: string[];
    initial_files?: Record<string, string>;
    attempt_policy?: {
      max_attempts?: number;
      pass_threshold?: number;
      multipliers?: number[];
      hints?: string[];
      preserve_workspace?: boolean;
    };
    metadata?: {
      difficulty?: number;
      estimated_minutes?: number;
      capability?: string;
      private_validation?: boolean;
      instance_count?: number;
      task_count?: number;
      suite_kind?: string;
      manual_scoring?: boolean;
      source_repository?: string;
      source_commit?: string;
      source_path?: string;
      suite_revision?: string;
    };
    rubric?: ManualRubric;
  };
}

export interface ManualRubricDimension {
  key: string;
  label: string;
  max_score: number;
  criteria: string;
}

export interface ManualRubric {
  mode: "manual";
  version: string;
  dimensions: ManualRubricDimension[];
  checklist: Array<{ key: string; label: string }>;
  critical_defects: Array<{ key: string; label: string }>;
}

export interface ManualReview {
  id: string;
  run_id: string;
  status: "draft" | "submitted";
  rubric_version: string;
  reviewer: string;
  dimension_scores: Record<string, number>;
  checklist: Record<string, boolean>;
  critical_defects: string[];
  comment: string;
  evidence: Array<{ name: string; path: string; size: number }>;
  total_score?: number | null;
  updated_at: string;
  submitted_at?: string | null;
}

export interface MathPaperImport {
  id: string;
  status: "needs_review" | "ready_to_publish" | "published" | string;
  exam: string;
  year: number;
  title: string;
  source: {
    filename: string;
    sha256: string;
    size_bytes: number;
    page_count: number;
  };
  questions?: Array<{
    number: number;
    type: "choice" | "fill" | "solution";
    points: number;
    question_text: string;
    answer?: string | null;
    accepted_answers?: string[];
    variables?: string[];
    solution_obligations?: string[];
    source_pages?: number[];
    detection_confidence?: string;
    review_status: string;
  }>;
  warnings: string[];
  detected_questions?: number;
  confirmed_questions?: number;
  published_suites?: Array<{ id: string; lane: string; name: string; case_count: number }>;
}

export interface Suite {
  id: string;
  name: string;
  description: string;
  version: string;
  case_count: number;
  builtin: number;
  difficulty_min?: number;
  difficulty_max?: number;
  category_count?: number;
  docker_case_count?: number;
  judge_case_count?: number;
}

export interface SuiteCasePreview {
  id: string;
  slug: string;
  title: string;
  description: string;
  category: string;
  difficulty?: number;
  estimated_minutes?: number;
  requires_docker?: boolean;
  instruction: string;
}

export interface Participant {
  model_id: string;
  runner_id: string;
}

export interface Experiment {
  id: string;
  name: string;
  suite_id: string;
  suite_name: string;
  participants: Participant[];
  repetitions: number;
  concurrency: number;
  reasoning_policy?: ReasoningPolicy;
  reasoning_effort?: ReasoningEffort | null;
  strict_fairness?: boolean;
  judge_reasoning_effort?: ReasoningEffort | null;
  runtime_config_version?: string;
  status: string;
  run_count?: number;
  finished_count?: number;
  avg_score?: number | null;
  weighted_score?: number | null;
  exam_score?: number | null;
  exam_total?: number | null;
  exam_scoring_basis?: "answer_quality" | string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  suite_metadata?: {
    kind: "benchmark" | "frontend";
    manual_scoring?: boolean;
    source_repository?: string;
    source_commit?: string;
    suite_revision?: string;
  };
  summary?: {
    total: number;
    completed: number;
    failed: number;
    blocked: number;
    avg_score?: number | null;
    weighted_score?: number | null;
    exam_score?: number | null;
    exam_total?: number | null;
    exam_scoring_basis?: "answer_quality" | string;
    avg_objective_score?: number | null;
    avg_judge_score?: number | null;
    avg_time_score?: number | null;
    avg_token_score?: number | null;
    cost_usd?: number;
    tokens?: number;
    unpriced_runs?: number;
    reviewed_runs?: number;
    unreviewed_runs?: number;
    review_progress?: number;
    reviewed_weighted_score?: number | null;
    frontend_weighted_score?: number | null;
  };
}

export interface RunSummary {
  id: string;
  experiment_id: string;
  test_case_id: string;
  model_id: string;
  runner_id: string;
  test_title: string;
  category: string;
  model_name: string;
  runner_name: string;
  lane: "unified" | "native";
  repetition: number;
  status: string;
  score?: number | null;
  objective_score?: number | null;
  judge_score?: number | null;
  time_score?: number | null;
  step_score?: number | null;
  token_score?: number | null;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  cost_source: "reported" | "configured" | "unpriced" | "unavailable" | string;
  duration_ms: number;
  steps: number;
  attempt_count: number;
  passed?: boolean | null;
  workspace_path?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_code?: string;
  error_message?: string;
  requested_reasoning_effort?: ReasoningEffort | null;
  effective_reasoning_effort?: string | null;
  effort_source?: string;
  effort_verified?: boolean;
  runtime_identity?: Record<string, unknown>;
  telemetry_status?: "pending" | "reported" | "partial" | "unavailable" | "unknown" | string;
  failure_class?: "agent_solution_failure" | "agent_timeout" | "runtime_environment_failure" | "validator_infrastructure_failure" | "permission_mismatch" | string | null;
  created_at: string;
}

export interface RunEvent {
  id: number;
  seq: number;
  event_type: string;
  payload: JsonObject;
  created_at: string;
}

export interface ValidatorResult {
  id: string;
  validator_type: string;
  weight: number;
  score: number;
  status: string;
  evidence: JsonObject;
}

export interface ScoreDimension {
  id: string;
  dimension: "objective_quality" | "judge_quality" | "manual_quality" | "time_efficiency" | "step_efficiency" | string;
  score: number;
  weight: number;
  evidence: JsonObject;
}

export interface Artifact {
  id: string;
  kind: string;
  name: string;
  path: string;
  size: number;
  sha256: string;
}

export interface RunAttempt {
  id: string;
  run_id: string;
  attempt_no: number;
  status: string;
  prompt: string;
  multiplier: number;
  raw_score?: number | null;
  adjusted_score?: number | null;
  passed: boolean;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  duration_ms: number;
  steps: number;
  error_code?: string | null;
  error_message?: string | null;
  result: JsonObject;
  created_at: string;
  completed_at?: string | null;
}

export interface RunDetail extends RunSummary {
  final_answer?: string;
  error_code?: string;
  error_message?: string;
  events: RunEvent[];
  validators: ValidatorResult[];
  score_dimensions: ScoreDimension[];
  artifacts: Artifact[];
  attempts: RunAttempt[];
  judge_reviews: Array<{
    id: string;
    score?: number;
    status: string;
    reasoning_effort?: string | null;
    runtime_identity?: Record<string, unknown>;
    evidence: JsonObject;
  }>;
  test_definition?: Omit<NonNullable<TestCase["definition"]>, "instruction"> & { instruction?: string | null };
  materials?: { name: string; size_bytes: number }[];
  runner_type: string;
  model_name: string;
  frontend?: {
    difficulty: number;
    source_repository: string;
    source_commit: string;
    source_path: string;
    suite_revision: string;
    preview_entry: string;
    rubric: ManualRubric;
    review?: ManualReview | null;
  };
}

export interface FrontendPreview {
  available: boolean;
  kind: "static" | "project" | "none";
  entry?: string;
  url?: string;
  scripts?: string[];
  reason?: string;
}

export interface FrontendPortfolioRun {
  id: string;
  model_id: string;
  runner_id: string;
  repetition: number;
  status: string;
  score?: number | null;
  workspace_path?: string | null;
  duration_ms: number;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  model_name: string;
  runner_name: string;
  title: string;
  slug: string;
  difficulty: number;
  preview: FrontendPreview;
  review?: ManualReview | null;
}

export interface FrontendPortfolio {
  experiment_id: string;
  root_path: string;
  metadata: NonNullable<Experiment["suite_metadata"]>;
  score: {
    reviewed_runs: number;
    unreviewed_runs: number;
    review_progress: number;
    reviewed_weighted_score?: number | null;
    frontend_weighted_score?: number | null;
  };
  runs: FrontendPortfolioRun[];
}

export interface DashboardData {
  total_runs: number;
  active_runs: number;
  avg_score?: number | null;
  total_cost?: number | null;
  total_tokens?: number | null;
  unpriced_runs?: number | null;
  models: number;
  test_cases: number;
  recent_experiments: Experiment[];
  categories: Array<{ category: string; count: number }>;
}

export interface SystemStatus {
  version: string;
  data_dir: string;
  workspaces_dir?: string;
  database: { path: string; ready: boolean };
  docker: { installed: boolean; available: boolean; executable?: string };
  native_cli_enabled: boolean;
  settings: {
    judge_model_id?: string | null;
    judge_runner_id?: string | null;
    default_concurrency: number;
    default_max_runtime_seconds: number;
  };
  runners: Array<{
    id: string;
    name: string;
    capability: {
      installed: boolean;
      version?: string;
      error?: string;
      warning?: string;
      install_command?: string;
      desktop_installed?: boolean;
    };
  }>;
}

export interface ProfileDimension {
  category: string;
  avg_score: number;
  runs: number;
  success_rate: number;
}

export interface ModelProfile {
  model_id: string;
  model_name: string;
  provider: string;
  total_runs: number;
  avg_score: number;
  success_rate: number;
  last_run_at: string;
  dimensions: ProfileDimension[];
}

export interface LeaderboardRow {
  model_id: string;
  runner_id: string;
  model_name: string;
  runner_name: string;
  lane: string;
  runs: number;
  avg_score: number;
  avg_objective_score?: number | null;
  avg_time_score?: number | null;
  avg_token_score?: number | null;
  success_rate: number;
  avg_duration_ms: number;
  total_cost: number;
  avg_tokens: number | null;
  telemetry_runs?: number;
}

export interface ExamLeaderboardRow {
  model_id: string;
  runner_id: string;
  model_name: string;
  runner_name: string;
  board: "math-2025" | "ncre";
  mode: "closed-book" | "tool-augmented" | "office";
  papers: number;
  exam_total: number;
  avg_exam_score: number;
  best_exam_score: number;
  benchmark_score: number;
  benchmark_rate: number;
  avg_duration_ms: number;
  avg_tokens: number;
  total_cost: number;
}
