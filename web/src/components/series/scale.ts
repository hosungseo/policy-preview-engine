// Shared horizontal scale so the line chart and the effect strip line up.
// Wide screens: real announcement dates. Phones: evenly spread and numbered, so close dates never collide.
export const DAY = 86_400_000;

export function dims(wide: boolean) {
  return { W: wide ? 960 : 360, l: 44, r: wide ? 120 : 48 };
}

export function xScale(dates: string[], wide: boolean): (i: number) => number {
  const { W, l, r } = dims(wide);
  const t = dates.map((d) => Date.parse(d));
  const t0 = t[0] - 20 * DAY;
  const t1 = t[t.length - 1] + 25 * DAY;
  return (i) => (wide ? l + ((t[i] - t0) / (t1 - t0)) * (W - l - r)
    : l + 12 + (i / Math.max(1, dates.length - 1)) * (W - l - r - 24));
}

export function quarterTicks(dates: string[]): string[] {
  const first = new Date(Date.parse(dates[0]) - 20 * DAY);
  const last = new Date(Date.parse(dates[dates.length - 1]) + 25 * DAY);
  const out: string[] = [];
  for (let y = first.getUTCFullYear(); y <= last.getUTCFullYear(); y++) {
    for (const m of [1, 4, 7, 10]) {
      const d = `${y}-${String(m).padStart(2, "0")}-01`;
      if (Date.parse(d) > first.getTime() && Date.parse(d) < last.getTime()) out.push(d);
    }
  }
  return out;
}
