// Mirrors engine/pp/export.py bundle.json. Keep in sync with the engine.
export type Support = -2 | -1 | 0 | 1 | 2;
export type Channel = "filter" | "fts" | "semantic";

export interface Segment { id: string; label: string; text: string; start: number; end: number }

export interface Persona {
  uuid: string; panel: "rep" | "aff"; found_by: Channel[]; name: string; sex: string; age: number;
  age_band: string; province: string; region: string; district: string; occupation: string;
  occupation_major: string; education_level: string; marital_status: string; family_type: string;
  family: string; housing_type: string; summary: string; detail: string; similar: string[];
  jev?: JevPersona | null;
}
export interface MethodProb { key: string; label: string; p: number }
export interface JevPersona {
  stance: number; reserve: number; direct: number; comment: number;
  oppose_most?: { segment_id: string; p: number }; understand?: number; best_method?: MethodProb;
}

export interface Reaction {
  rid: string; uuid: string; support: Support; impact: "직접" | "간접" | "무관"; trigger_quote: string;
  quote_verified: boolean; segment_id: string | null; quote_span: [number, number] | null; reason: string;
  concerns: string[]; hopes: string[]; suggestion: string; would_comment: boolean; channel: string;
  jev_read?: number; flagged?: boolean; lenses?: string[];
}

export interface Overall { n: number; mean: number | null; dist: Record<string, number>; ci95: [number, number] | null }
export interface GroupRow { group: string; n: number; mean: number; oppose: number; favor: number; small: boolean }
export interface SegmentHeat {
  segment_id: string; mentions: number; mean: number | null; oppose: number; favor: number; top_concerns: string[];
}
export interface PanelIssueCount { n: number; denominator: number; share: number | null; mean: number | null; caution?: string }
export interface Issue {
  id: string; title: string; stance: "우려" | "기대" | "혼재"; summary: string; member_ids: string[]; n: number;
  share: number | null; mean: number | null; by_panel?: { rep: PanelIssueCount; aff: PanelIssueCount }; basis?: "rep";
  groups: { kind: string; group: string; count: number; lift: number }[];
  quotes: { rid: string; uuid: string; text: string }[]; segments: string[];
  member_probs?: Record<string, number>;
  k?: number; jev_mean?: number; jev_leaders?: IssueLeader[];
}
export interface IssueLeader { kind: string; group: string; n: number; mean: number; lift: number }
export interface OutreachSuggestion { method: string; where: string; when: string; why: string }
export interface Outreach {
  panel?: "rep" | "aff"; caution?: string;
  kind: string; group: string; n: number; direct: number; oppose: number; silent: number; score: number;
  channels: string[]; member_uuids: string[]; sample_quotes: string[]; sample_uuids?: string[]; suggestion: OutreachSuggestion;
  methods?: MethodProb[];
}
export interface JevGroupRow {
  group: string; n: number; mean: number; reserve: number; direct: number; comment: number; small: boolean;
}
export interface JevClauseRow { group: string; n: number; small: boolean; values: Record<string, number> }
export interface JevCompare {
  n: number; llm_dist?: Record<string, number>; llm_mean?: number; llm_favor?: number; llm_reserve?: number;
  jev_mass?: number[]; jev_mean?: number; jev_favor?: number; jev_reserve?: number; corr?: number | null;
}
export interface JevAnalysis {
  n: number;
  overall: { n: number; mean: number | null; ci95: [number, number] | null; mass: number[] };
  by_group: Record<string, JevGroupRow[]>;
  clauses: { overall: Record<string, number>; groups: Record<string, JevClauseRow[]> };
  channels: { key: string; label: string; n: number; share: number }[];
  compare: JevCompare;
  positions?: { overall: Record<string, { mean: number; oppose: number; support: number }>;
    groups: Record<string, JevPositionRow[]> } | null;
  issue_prevalence?: { overall: Record<string, number>; groups: Record<string, JevClauseRow[]>;
    leaders: Record<string, IssueLeader[]> } | null;
  methods?: MethodProb[] | null;
  methods_by_group?: Record<string, JevClauseRow[]> | null;
  explain?: { overall: Record<string, number>; top: string | null;
    understand: { overall: number; education_level: UnderstandRow[]; age_band: UnderstandRow[] } } | null;
  provinces?: { province: string; n: number; mean: number; reserve: number; direct: number }[];
}
export interface JevPositionRow extends JevClauseRow { oppose: Record<string, number> }
export interface UnderstandRow { group: string; n: number; small: boolean; mean: number }
export interface AltCell {
  group: string; n: number; small: boolean; d_favor: number; d_reserve: number; d_mean: number;
  net_favor?: number; net_reserve?: number; net_mean?: number;
}
export interface Alternative {
  id: string; title: string; text: string; segment_id: string | null;
  source_title: string; source_n: number; source_n_aff?: number; source_example: string;
  n: number; favor: number; reserve: number; mean: number; d_favor: number; d_reserve: number; d_mean: number;
  net_favor?: number; net_reserve?: number; net_mean?: number;
  groups: Record<string, AltCell[]>; movers: (AltCell & { kind: string })[];
}
export interface Alternatives {
  n: number; placebo_text?: string;
  baseline: { n: number; favor: number; reserve: number; mean: number };
  placebo: { n: number; d_favor: number; d_reserve: number; d_mean: number } | null;
  items: Alternative[];
}
export interface Consistency {
  n: number; flagged: number; threshold: number; mean_abs_diff: number | null; corr: number | null;
  items: { rid: string; llm: number; jev: number; diff: number }[]; by_rid: Record<string, number>;
}
export interface SuggestionGroup { title: string; stance: string; summary: string; member_ids: string[]; n: number; n_aff?: number; example: string }
export interface Analysis {
  overall: Overall; overall_aff: Overall; by_group: Record<string, GroupRow[]>; segments_heat: SegmentHeat[];
  issues: Issue[]; unassigned: number; suggestions: SuggestionGroup[]; outreach: Outreach[]; insights: string[];
  outreach_source?: "jev" | "llm"; jev?: JevAnalysis | null;
  alternatives?: Alternatives | null; consistency?: Consistency | null;
  quality?: Quality; lenses?: { items: LensItem[]; threshold: number };
  clarity?: { clauses: number; flagged: number; worst: { segment_id: string; flags: string[] } | null; missing: string[] };
}
export interface Turn { round: number; speaker: string; text: string }
export interface HearingRead { index: number; round: number; speaker: string; stance: number; marks: Record<string, number> }
export interface Hearing {
  policy_truncated?: boolean; shown_chars?: number; total_chars?: number; context_note?: string;
  participants: string[]; agenda: string[]; turns: Turn[];
  summary: { agreements: string[]; disagreements: string[]; missing: string[] };
  reads?: HearingRead[];
  trajectories?: { participants: { uuid: string; stances: Record<string, number>; change: number }[];
    movers: string[]; counts: Record<string, number>; move: number };
}
export interface ClarityClause { segment_id: string; values: Record<string, number>; flags: string[] }
export interface Clarity {
  indicators: { key: string; label: string }[]; clauses: ClarityClause[];
  document: { key: string; label: string; p: number }[]; threshold: number;
}
export interface Quality {
  order: { reactions: number; same_choice: number; agreement: number | null; flips: number; assigned: number;
    mean_shift: number | null; threshold: number };
  batching: { n: number; mean_abs_diff: number | null; max_abs_diff: number | null; corr: number | null };
  repeat: { n: number; stance_mean_abs_diff: number | null; stance_max_abs_diff: number | null;
    direct_mean_abs_diff: number | null; channel_same: number | null };
  occupations: { n: number; agree: number; share: number | null; examples: { occupation: string; jev: string; llm: string }[] };
}
export interface LensItem { key: string; label: string; n: number; share: number; mean_support: number | null }
export interface PlanDoc {
  overview: { title: string; kind: string; agency: string; panel: string; created_at: string };
  issues: { id: string; title: string; stance: string; n: number; share: number | null; mean: number | null; summary: string;
    by_panel?: { rep: PanelIssueCount; aff: PanelIssueCount };
    segments: string[]; groups: string[]; quote: string; jev_mean?: number }[];
  outreach: { kind: string; group: string; n: number; direct: number; oppose: number; silent: number; panel?: string; caution?: string;
    channels: string[]; suggestion: OutreachSuggestion; methods?: MethodProb[] }[];
  qa: { question: string; answer: string; issue_id: string; jev_p?: number; jev_n?: number; jev_leaders?: IssueLeader[] }[];
  suggestions: { title: string; n: number; n_aff?: number; example: string }[];
  alternatives?: (Pick<Alternative, "id" | "title" | "text" | "source_title" | "source_n" | "source_example" | "n"
    | "d_favor" | "d_reserve" | "d_mean" | "net_favor" | "net_reserve" | "net_mean"> & { movers: (AltCell & { kind: string })[] })[];
  explain?: { clauses: { segment_id: string; label: string; p: number }[]; understand: number;
    hardest: { group: string; mean: number } | null } | null;
  clarity?: { clauses: { segment_id: string; label: string; flags: { key: string; label: string; p: number }[] }[];
    missing: { key: string; label: string; p: number }[] } | null;
  limits: string[];
}
export interface Population {
  total: number; province: Record<string, number>; region: Record<string, number>; sex: Record<string, number>;
  age_band: Record<string, number>; family: Record<string, number>; housing_type: Record<string, number>;
  education_level: Record<string, number>;
}
export interface PanelInfo {
  representative: { n: number; strata: string[]; seed: number };
  affected: {
    n: number;
    spec: { filters: Record<string, unknown>[]; keywords: string[]; semantic_query: string; rationale: string };
    channels: Record<Channel, number>;
    semantic_note?: string;
  };
}
export interface IssueAssignment {
  reactions: number; llm_assigned: number; jev_assigned: number; both: number; agreement: number | null; threshold: number;
}
export interface Meta {
  provider: string; models: { react: string; synth: string; jev?: string }; created_at: string;
  stages: { name: string; started_at: string; seconds: number }[];
  counts: {
    react_calls?: number; reactions?: number; failed?: number; quote_mismatch?: number;
    jev_calls?: number; jev_scored?: number; jev_failed?: number;
    issue_assignment?: IssueAssignment;
  };
  fallbacks: string[];
  jev_usage?: Record<string, Record<string, JevUsage>>;
}
export interface JevUsage { calls: number; input_tokens: number; call_seconds: number; cost_usd: number; cached?: number }
export interface Bundle {
  id: string; title: string; kind: string; agency: string;
  source: { url?: string; period?: string; note?: string; extra?: string[] };
  policy_text: string; segments: Segment[]; population: Population | Record<string, never>; panel: PanelInfo;
  personas: Persona[]; reactions: Reaction[]; analysis: Analysis; hearing: Hearing; plan: PlanDoc; meta: Meta;
  clarity?: Clarity | null;
}
export interface RunSummary {
  id: string; title: string; kind: string; agency: string; created_at: string; n_rep: number; n_aff: number;
  n_issues: number; top_issue: string; seconds: number; dev?: boolean;
}
