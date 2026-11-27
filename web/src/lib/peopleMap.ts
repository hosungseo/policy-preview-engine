// The 100만 명 지도 bundle (`python -m pp peoplemap`): every persona as a dot, the series panel on top.
// Files live under public/series/<id>-map/ and are fetched in the browser (they are too big for the page).

export interface MapDistrict { k: string; name: string; s: number; n: number; cx: number; cy: number }
export interface MapMeasure { id: string; short: string; date: string; title: string; agency: string; favor: number }
export interface MapMeta {
  version: number;
  series: string;
  source: string;
  quant: number;
  n_dots: number;
  width_km: number;
  height_km: number;
  districts: MapDistrict[];
  outlines: { sido: string[]; seoul: { n: string; d: string }[] };
  panel: { n: number; m: number; chunk: number; files: string[]; condition: string };
  measures: MapMeasure[];
  tenure_labels: string[];
  sizes: Record<string, number>;
}

export interface MapData {
  meta: MapMeta;
  x: Float32Array;        // km east, one per persona (DB order: district, id)
  y: Float32Array;        // km south
  dist: Uint16Array;      // district index per persona
  idx: Uint32Array;       // panel person -> persona
  ten: Uint8Array;        // panel tenure: 0 own, 1 jeonse, 2 monthly, 3 other; +4 owns two homes or more
  fav: Uint8Array;        // % leaning in favour, measure-major (m × n)
  opp: Uint8Array;        // % leaning against
  province: string[];     // panel person -> DB province prefix ("서울", "경기", …)
}

export interface Person {
  district: string;
  age: number;
  sex: string;
  occupation: string;
  family: string;
  housing: string;
  text: string;
}

async function fetchBytes(url: string, onProgress?: (loaded: number) => void): Promise<Uint8Array> {
  const res = await fetch(url);
  if (!res.ok || !res.body) throw new Error(`${url}: ${res.status}`);
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress?.(loaded);
  }
  const out = new Uint8Array(loaded);
  let at = 0;
  for (const c of chunks) { out.set(c, at); at += c.length; }
  return out;
}

export async function loadMap(base: string, onProgress?: (share: number) => void): Promise<MapData> {
  const meta = (await (await fetch(`${base}/meta.json`)).json()) as MapMeta;
  const total = (meta.sizes["dots.bin"] ?? 0) + (meta.sizes["panel.bin"] ?? 0);
  let doneDots = 0;
  const [dots, panel] = await Promise.all([
    fetchBytes(`${base}/dots.bin`, (l) => { doneDots = l; onProgress?.(l / total); }),
    fetchBytes(`${base}/panel.bin`, (l) => onProgress?.((doneDots + l) / total)),
  ]);
  const q = new Uint16Array(dots.buffer, dots.byteOffset, dots.byteLength / 2);
  const N = meta.n_dots, Q = meta.quant;
  const x = new Float32Array(N), y = new Float32Array(N), dist = new Uint16Array(N);
  for (let i = 0; i < N; i++) { x[i] = q[2 * i] / Q; y[i] = q[2 * i + 1] / Q; }
  meta.districts.forEach((d, j) => dist.fill(j, d.s, d.s + d.n));
  const { n, m } = meta.panel;
  const buf = panel.buffer.slice(panel.byteOffset, panel.byteOffset + panel.byteLength);
  const idx = new Uint32Array(buf, 0, n);
  const ten = new Uint8Array(buf, n * 4, n);
  const fav = new Uint8Array(buf, n * 5, m * n);
  const opp = new Uint8Array(buf, n * 5 + m * n, m * n);
  const province = Array.from(idx, (i) => meta.districts[dist[i]].k.split("-")[0]);
  return { meta, x, y, dist, idx, ten, fav, opp, province };
}

const chunkCache = new Map<string, Promise<unknown[][]>>();

export async function loadPerson(base: string, data: MapData, k: number): Promise<Person> {
  const { chunk, files } = data.meta.panel;
  const file = files[Math.floor(k / chunk)];
  if (!chunkCache.has(file)) chunkCache.set(file, fetch(`${base}/${file}`).then((r) => r.json() as Promise<unknown[][]>));
  const row = (await chunkCache.get(file)!)[k % chunk] as [number, number, number, string, string, string, string];
  const [d, age, sex, occupation, family, housing, text] = row;
  return { district: data.meta.districts[d].name, age, sex: sex ? "여자" : "남자", occupation, family, housing, text };
}

export interface Shares { n: number; favor: number; neutral: number; oppose: number }

// Mean probabilities (0–1) of leaning in favour / neutral / against for measure m among panel people matching sel.
export function shares(data: MapData, m: number, sel: (k: number) => boolean): Shares {
  const n0 = data.meta.panel.n;
  let n = 0, f = 0, o = 0;
  for (let k = 0; k < n0; k++) {
    if (!sel(k)) continue;
    n++; f += data.fav[m * n0 + k]; o += data.opp[m * n0 + k];
  }
  if (!n) return { n: 0, favor: 0, neutral: 0, oppose: 0 };
  return { n, favor: f / n / 100, oppose: o / n / 100, neutral: 1 - (f + o) / n / 100 };
}

export const tenureOf = (data: MapData, k: number) => data.ten[k] & 3;
export const multiOf = (data: MapData, k: number) => (data.ten[k] & 4) !== 0;
export const CAPITAL = new Set(["서울", "경기", "인천"]);
