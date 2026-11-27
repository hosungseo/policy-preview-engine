// Diverging support scale from KRDS ramps (point = oppose, primary = favour, gray midpoint).
// Both arms validated as ordinal ramps with the dataviz validator; see the plan's Part C intro.
export const SUPPORT_COLOR: Record<string, string> = {
  "-2": "#d63d4a", "-1": "#e0858c", "0": "#b1b8be", "1": "#86aff9", "2": "#256ef4",
};
export const SUPPORT_INK: Record<string, string> = {
  "-2": "#ffffff", "-1": "#1e2124", "0": "#1e2124", "1": "#1e2124", "2": "#ffffff",
};
export const NEGATIVE = "#d63d4a";
export const POSITIVE = "#256ef4";
export const MUTED = "#cdd1d5";
export const PRIMARY = "#256ef4";

export const MEAN_BINS = [
  { label: "−1 이하", color: "#d63d4a" },
  { label: "−1 ~ −0.3", color: "#e0858c" },
  { label: "−0.3 ~ +0.3", color: "#e6e8ea" },
  { label: "+0.3 ~ +1", color: "#86aff9" },
  { label: "+1 이상", color: "#256ef4" },
];

export function meanFill(mean: number | null | undefined): string {
  if (mean === null || mean === undefined) return "#f4f5f6";
  if (mean <= -1) return MEAN_BINS[0].color;
  if (mean <= -0.3) return MEAN_BINS[1].color;
  if (mean < 0.3) return MEAN_BINS[2].color;
  if (mean < 1) return MEAN_BINS[3].color;
  return MEAN_BINS[4].color;
}

export function meanInk(mean: number | null | undefined): string {
  return mean !== null && mean !== undefined && (mean <= -1 || mean >= 1) ? "#ffffff" : "#1e2124";
}

// Sequential single-hue ramp (KRDS primary 30→70) for probabilities 0..1, e.g. clause impact.
// Validated as an ordinal ramp: monotone lightness, adjacent ΔL >= 0.06, light end 2.21:1 on white.
export const SEQ_BINS = [
  { max: 0.2, color: "#86aff9", ink: "#1e2124", label: "20% 미만" },
  { max: 0.35, color: "#4c87f6", ink: "#ffffff", label: "20~35%" },
  { max: 0.5, color: "#256ef4", ink: "#ffffff", label: "35~50%" },
  { max: 0.65, color: "#0b50d0", ink: "#ffffff", label: "50~65%" },
  { max: 1.01, color: "#083891", ink: "#ffffff", label: "65% 이상" },
];

export function seqBin(p: number) {
  return SEQ_BINS.find((b) => p < b.max) ?? SEQ_BINS[SEQ_BINS.length - 1];
}

// The same validated diverging colours for an expected position on a -1..+1 scale
// (provision stance) and for paired changes (amendment effects on the -2..+2 stance scale).
export const POSITION_BINS = [
  { max: -0.5, color: "#d63d4a", ink: "#ffffff", label: "−0.5 이하(반대 쪽)" },
  { max: -0.15, color: "#e0858c", ink: "#1e2124", label: "−0.5 ~ −0.15" },
  { max: 0.15, color: "#e6e8ea", ink: "#1e2124", label: "−0.15 ~ +0.15" },
  { max: 0.5, color: "#86aff9", ink: "#1e2124", label: "+0.15 ~ +0.5" },
  { max: Infinity, color: "#256ef4", ink: "#ffffff", label: "+0.5 이상(찬성 쪽)" },
];
export const DELTA_BINS = [
  { max: -0.2, color: "#d63d4a", ink: "#ffffff", label: "−0.2 이하" },
  { max: -0.05, color: "#e0858c", ink: "#1e2124", label: "−0.2 ~ −0.05" },
  { max: 0.05, color: "#e6e8ea", ink: "#1e2124", label: "±0.05 안" },
  { max: 0.2, color: "#86aff9", ink: "#1e2124", label: "+0.05 ~ +0.2" },
  { max: Infinity, color: "#256ef4", ink: "#ffffff", label: "+0.2 이상" },
];

export function binOf<T extends { max: number }>(bins: T[], v: number): T {
  return bins.find((b) => v <= b.max) ?? bins[bins.length - 1];
}

// Two conditions of the series line chart; validated as a pair (CVD dE 14.9, normal 16.6).
export const SERIES_COLOR = { alone: "#256ef4", context: "#4a3aa7" } as const;

// Gap from the measure's national value (or a paired change), in probability units.
export const GAP_BINS = [
  { color: "#d63d4a", ink: "#ffffff", label: "전국보다 5%p 이상 낮음" },
  { color: "#e0858c", ink: "#1e2124", label: "2~5%p 낮음" },
  { color: "#e6e8ea", ink: "#1e2124", label: "±2%p 안" },
  { color: "#86aff9", ink: "#1e2124", label: "2~5%p 높음" },
  { color: "#256ef4", ink: "#ffffff", label: "5%p 이상 높음" },
];

export function gapBin(gap: number) {
  if (gap <= -0.05) return GAP_BINS[0];
  if (gap <= -0.02) return GAP_BINS[1];
  if (gap < 0.02) return GAP_BINS[2];
  if (gap < 0.05) return GAP_BINS[3];
  return GAP_BINS[4];
}
