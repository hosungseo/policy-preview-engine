export interface GroupStat { group: string; n: number; favor: number; reserve: number; mean: number; small: boolean }
export interface GroupDiff { group: string; n: number; diff: number; small: boolean }
export interface HousingGroup { group: string; n: number; small: boolean; values: Record<string, number> }
// The same people without and with their housing information: [before, after] shares leaning in favour and against.
export interface PairStat { n: number; favor: [number, number]; oppose: [number, number] }
export interface BeforeAfter { overall: PairStat; groups: Record<string, (PairStat & { group: string; small: boolean })[]> }

export interface ConditionStats {
  n: number; favor: number; favor_ci95: [number, number] | null; reserve: number; mean: number; mass: number[];
  groups: Record<string, GroupStat[]>;
  positions: Record<string, { mean: number; oppose: number; support: number }>;
  housing: Record<string, number>;
  housing_groups: Record<string, HousingGroup[]>;
}

export interface SeriesMeasure {
  id: string; date: string; short: string; title: string; agency: string; summary: string; text: string;
  // title/provider/license name the original; text_kind "summary" means `text` is our summary, not the original.
  source: { url: string; file?: string; note?: string; title?: string; provider?: string; license?: string;
    text_kind?: "summary" };
  segments: { id: string; label: string }[];
  conditions: { alone: ConditionStats; context: ConditionStats };
  effect: { overall: { n: number; diff: number; ci95: [number, number] | null }; groups: Record<string, GroupDiff[]> };
  top_reserve: { kind: string; group: string; reserve: number } | null;
  housing_examples?: { label: string; text: string }[];
  before_after?: BeforeAfter;
}

export interface SeriesUsage { calls: number; input_tokens: number; call_seconds: number; cost_usd: number; cached?: number }

export interface SeriesBundle {
  id: string; title: string; subtitle: string; created_at: string; provider: string; dev?: boolean;
  panel: { n: number; seed: number; strata: string[] };
  order: Record<string, string[]>; kind_label: Record<string, string>; housing_labels: Record<string, string>;
  measures: SeriesMeasure[];
  tenure: {
    labels: Record<string, string>; overall: Record<string, number>;
    provinces: { province: string; n: number; own: number; official_own: number | null }[];
    official: { year: number; survey?: string; unit?: string; publisher?: string; source: string; note?: string;
      national?: { own: number; rent: number; free: number } };
  };
  regulated: { periods: { from: string; areas: string[]; partial: string[]; source: string;
    evidence?: { url: string; text: string; kind?: "summary"; license?: string; title?: string; provider?: string;
      page?: string }[] }[] };
  // Present when tenure was assigned from official statistics and each question carried local housing facts.
  housing_context?: { tenure: string; tenure_note: string; market_note: string; price_band_note?: string | null;
    panel_from?: string | null; tenure_before?: Record<string, number> };
  meta: { jev_usage: Record<string, Record<string, SeriesUsage>>; stages: { name: string; seconds: number }[];
    jev_model: string; failures: Record<string, number> };
}
