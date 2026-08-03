export type JsonObject = Record<string, unknown>;

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
  | "qoder-cli";

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
    };
  };
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
  status: string;
  run_count?: number;
  finished_count?: number;
  avg_score?: number | null;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  summary?: {
    total: number;
    completed: number;
    failed: number;
    blocked: number;
    avg_score?: number | null;
    avg_objective_score?: number | null;
    avg_judge_score?: number | null;
    avg_time_score?: number | null;
    avg_token_score?: number | null;
    cost_usd?: number;
    tokens?: number;
    unpriced_runs?: number;
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
  error_code?: string;
  error_message?: string;
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
  dimension: "objective_quality" | "judge_quality" | "time_efficiency" | "step_efficiency" | string;
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
    evidence: JsonObject;
  }>;
  test_definition: TestCase["definition"];
  runner_type: string;
  model_name: string;
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
  avg_tokens: number;
}
