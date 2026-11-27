// Client for the ppservice API (engine/ppservice/app.py). Same-origin only; the cookie carries the session.

export class NoService extends Error {}
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public findings?: Finding[]) {
    super(message);
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-PP-Client"] = "web";
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { method, headers, credentials: "same-origin", cache: "no-store",
      body: init.body === undefined ? undefined : JSON.stringify(init.body) });
  } catch {
    throw new NoService("network");
  }
  const type = res.headers.get("content-type") ?? "";
  if (!type.includes("application/json")) {
    if (res.status >= 500) {
      throw new ApiError(res.status, "server_error", "서버에서 오류가 발생했습니다. 서버 터미널 로그와 패널·.env 설정을 확인해 주세요.");
    }
    throw new NoService("not json");
  }
  const data = await res.json();
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "error", err.message ?? "요청을 처리하지 못했습니다.", err.findings);
  }
  return data as T;
}

export interface Finding { code: string; level: "block" | "warn" | "info"; message: string; hint: string }
export interface Baseline { mae_pp: number; mae_max_pp: number; mae_band_pp: number; spread_ratio: number | null; worst_option_gap_pp: number; worst_item: string; spread_min: number | null; spread_max: number | null; items: number; n: number; source: string; jev_model: string; built_at: string }
export interface HistoricalBaseline {
  status: "verified"; evaluation_kind: "historical_diagnostic";
  mae_pp: number; worst_pp: number; reverse_mae_pp: number; question_ids: string[];
  scope: { min_age: number; year: number; population: string };
  inputs: { model: { model_revision: string } }; panel_version: string; source: string;
  model_identity_verified: false; unsure_signed_pp: number[]; excluded_reasons: string[]; artifact_hash: string;
}
export interface Accuracy {
  schema_version: 2; kind: "api_accuracy";
  payload: {
    state: "applied" | "not_applied" | "unverified" | "legacy";
    manifest_hash: string | null; model_revision: string | null; applied_rate: number | null;
    scope: { population: string; year: number; min_age: number; max_age: number | null; unit: "adult_person" } | null;
    baseline: { status: "verified" | "failed" | "incomplete"; mae_pp: number | null; worst_pp: number | null;
      inputs: { model: { model_revision: string } }; question_ids: string[]; scope: { min_age: number }; excluded_reasons: string[] } | null;
    historical_baseline?: HistoricalBaseline | null;
    reasons: string[];
  };
}
export function accuracyFor(result: Result): Accuracy["payload"] {
  return result.accuracy?.payload ?? { state: "legacy", manifest_hash: null, model_revision: null,
    applied_rate: null, scope: null, baseline: null, reasons: ["legacy_unversioned"] };
}

export function baselineFor(result: Result) {
  const accuracy = accuracyFor(result);
  const baseline = accuracy.baseline;
  return accuracy.state !== "legacy" && accuracy.state !== "unverified" && accuracy.model_revision
    && baseline?.status === "verified" && baseline.inputs.model.model_revision === accuracy.model_revision ? baseline : null;
}

export function historicalFor(result: Result) {
  const accuracy = accuracyFor(result);
  const historical = accuracy.historical_baseline;
  return accuracy.state === "not_applied" && historical?.status === "verified"
    && historical.evaluation_kind === "historical_diagnostic" ? historical : null;
}

export interface ServiceConfig {
  decision_model?: string; decision_provider?: string;
  model_profile?: ModelProfile;
  holdout?: { mae_pp: number; worst_pp: number; items: number; measured_on: string; model: string } | null;
  accuracy?: Accuracy;
  service: boolean; demo_login?: boolean; mock: boolean; n: number; daily_runs: number; retention_days: number;
  max_policy: number; max_question: number; max_option: number; panel_version: string; baseline: Baseline | null;
  future_available?: boolean; future_year?: number;
  setup_warnings?: string[];
}
/** "5년 뒤 보기": the same people asked with their base-year state block and with their projected state. */
export interface FutureView {
  year: number; version: string; n: number; dead: number; now_percent: number[]; future_percent: number[];
  shift_pp: number; format_shift_pp: number; threshold_pp: number; distinguishable: boolean;
  changed_n: number; shift_changed_pp: number | null; shift_unchanged_pp: number | null;
  changed_kinds: { working: number; province: number; marital: number; income_q: number };
  age_groups: { group: string; n: number; now_top: number; future_top: number; shift_pp: number }[];
}
/** "대상 규칙으로 나눠 보기": a rule judged on each member's 2025 and projected 2030 state; computed on request, never stored. */
export interface Rule {
  income_max_manwon: number | null; income_min_manwon: number | null; working: boolean | null;
  age_min: number | null; age_max: number | null; capital: boolean | null; note: string;
}
export interface RuleCount { n: number; pct: number; undetermined: number; total: number }
export interface RuleShift {
  n: number; now_top: number; future_top: number; shift_pp: number; threshold_pp: number; sampling_pp: number; distinguishable: boolean;
}
export interface RuleView {
  rule: Rule; rule_text: string; y2025: RuleCount; y2030: RuleCount;
  main_split: {
    in: { n: number; top: number }; out: { n: number; top: number }; diff_pp: number; threshold_pp: number;
    parts: { sampling: number; placebo: number; reversal: number }; distinguishable: boolean;
  } | null;
  main_small: string | null;
  future_split: { in: RuleShift | null; in_small: string | null; out: RuleShift | null; out_small: string | null };
  age_bands_2030: { group: string; n: number }[];
  lines: string[]; copy_text: string;
}
export interface AxisGroup { group: string; n: number; percent: number[] | null; top_percent: number }
export interface Axis {
  axis: string; groups: AxisGroup[]; high?: string; low?: string; diff_pp?: number; threshold_pp?: number; distinguishable?: boolean;
  parts?: { sampling: number; placebo: number; reversal: number };
}
export interface Result {
  accuracy?: Accuracy;
  n: number; options: string[]; percent: number[]; top: number; placebo_shift_pp: number; reversal_shift_pp: number;
  unstable: boolean; splits: { axis: string; high: string; low: string; diff_pp: number }[]; axes: Axis[];
  baseline: Baseline | null; next_action: { kind: "fix_question" | "ask_groups" | "real_survey"; text: string };
  lint_warnings: number; summary_text: string; cautions?: string[];
  addons?: { name: string; title: string }[];
  future?: FutureView | null;
}
export type RunStatus = "queued" | "running" | "succeeded" | "failed";
export interface Run {
  id: string; survey_id: string; status: RunStatus; status_label: string;
  spec: { title: string; policy_text: string; question: string; options: string[]; n: number; seed: number; future?: boolean };
  lint: Finding[]; done: number; total: number; failed: number; error_code: string | null; error_message: string | null;
  result: Result | null; retry_of: string | null; panel_version: string | null; jev_model: string | null; estimate_usd: number;
  created_at: string; started_at: string | null; finished_at: string | null;
}
export interface Survey { id: string; title: string; policy_text: string; created_at: string; runs: Run[] }
export interface SurveySummary { id: string; title: string; updated_at: string; n_runs: number; last_status: RunStatus | null;
  headline?: { option: string; percent: number; unstable: boolean } | null }

export const STATUS_LABEL: Record<string, string> = { queued: "접수됨", running: "응답 받는 중", succeeded: "완료", failed: "실패" };

export function kst(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

/** 심층 분석 (engine/ppservice/deep.py): the survey's own respondents heard one by one after the run. */
export interface DeepWho { name: string; age: number; sex: string; province: string; occupation: string }
export interface DeepVoice extends DeepWho { rid: string; reason: string; support: number; p: number }
export interface DeepResult {
  mock: boolean; models: Record<string, string>;
  counts: { heard: number; matched: number; representative: number; affected: number; checked: number };
  by_option: { option: string; n: number; share: number; mean_support: number | null; voices: DeepVoice[] }[];
  issues: { id: string; title: string; stance: string; summary: string; n: number; share: number | null; mean: number | null;
    by_panel?: { rep: { n: number }; aff: { n: number; share: number | null; caution?: string } };
    jev_mean: number | null; quotes: ({ text: string } & DeepWho)[] }[];
  outreach: { kind: string; group: string; n: number; channels: string[]; panel?: string; caution?: string;
    suggestion: { method?: string; where?: string; when?: string; why?: string } | null }[];
  alternatives: { title: string; text: string; source_example: string; n: number; d_favor: number; net_favor: number | null }[];
  insights: string[];
  coverage?: { step: string; planned: number; done: number; status: string }[];
  hearing: { agenda: string[]; summary: { agreements?: string[]; disagreements?: string[]; missing?: string[] } | null;
    turns: number; participants: number };
  qa: { question: string; answer: string }[]; limits: string[]; fallbacks: string[]; seconds: number; cost_usd: number;
}
export interface Deep {
  run_id: string; status: RunStatus; status_label: string; stage: string | null; stage_label: string;
  stage_index: number; stage_total: number; error_code: string | null; error_message: string | null;
  result: DeepResult | null; created_at: string; started_at: string | null; finished_at: string | null;
}

export interface Notice { mapping_lbic_id?: string; announce_type?: string; source?: "api" | "web"; seq: string; title: string; agency: string; kind: string; period: string; url: string }
export interface NoticeText extends Notice { text: string; full_length: number; clipped: boolean }

export interface ModelSlot { name: string; where: string }
export interface ModelProfile {
  kind: string; label: string; use: string; sentence: ModelSlot; decision: ModelSlot;
  choices: { kind: string; label: string; use: string }[];
}

/** 「찾아갈 곳」: groups whose stored answers differ enough to be worth meeting, and where they are. Computed on request. */
export interface VisitPlace { name: string; pct?: number; times?: number | null; n?: number }
export interface VisitCard {
  kind: "differ" | "unsure" | "split"; title: string; group: string; attribute: string; n: number;
  say: string; also: string | null; percent: number[];
  stat: { option: string; group_pct: number; rest_pct: number; diff_pp: number; threshold_pp: number;
    parts: { sampling: number; placebo: number; reversal: number } };
  /** source "1m": counted in the 1,000,000-person roster; "panel": counted among the people of this run's list. */
  where: { most: VisitPlace[]; dense: VisitPlace[]; districts: VisitPlace[]; source?: "1m" | "panel"; people?: number; of?: number } | null;
  venues: string[]; quiet: { group_pct: number; all_pct: number } | null; questions: string[]; basis: string;
}
export interface Visit {
  cards: VisitCard[]; missing: { who: string; route: string; party: boolean }[]; region_note: string | null;
  small: string | null; groups: number; tests: number; n: number; quiet_all_pct: number | null; roster_n?: number | null; method: string[]; copy_text: string;
}
