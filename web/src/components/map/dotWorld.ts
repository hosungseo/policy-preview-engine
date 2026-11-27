// The dot world: every persona is an ink dot on one canvas, the panel of 10,000 on a second canvas on top.
// Dots accumulate ink per pixel (dense places turn solid, sparse ones stay speckled). Camera flights zoom in log
// space. The panel can sit on the map or regroup into waffle bars; every change animates dot by dot.
// Only a dot's district is real; the spot inside it is an illustration.
import { CAPITAL, multiOf, tenureOf, type MapData } from "@/lib/peopleMap";

export type View = "map" | "tenure" | "region" | "waffle";
export interface Camera { x: number; y: number; z: number }   // centre (km) and zoom (CSS px per km)
export interface Label { x: number; y: number; text: string; sub?: string; value?: string; tone?: "fav" | "opp" | "neu"; align?: "left" | "right" | "center" }

type RGB = readonly [number, number, number];
const FAV: RGB = [37, 110, 244], NEU: RGB = [177, 184, 190], OPP: RGB = [214, 61, 74];
const INK: RGB = [30, 33, 36], DIM: RGB = [200, 205, 211], FOCUS: RGB = [120, 130, 142];
const CLS: RGB[] = [FAV, NEU, OPP];

const hash = (i: number, seed: number) => {
  let h = Math.imul(i ^ seed, 0x85ebca6b) ^ 0x9e3779b9;
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
};
const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
const smooth = (v: number) => v * v * (3 - 2 * v);
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

// ink per pixel -> opacity (1 - e^(-1.7 w)), tabulated
const LUT = new Uint8Array(2048);
for (let i = 0; i < 2048; i++) LUT[i] = Math.round(255 * (1 - Math.exp(-1.7 * (i / 128))));

class Layer {
  ctx: CanvasRenderingContext2D;
  W = 0; H = 0;
  w = new Float32Array(0); r = new Float32Array(0); g = new Float32Array(0); b = new Float32Array(0);
  img: ImageData | null = null; px = new Uint32Array(0);
  x0 = 0; y0 = 0; x1 = -1; y1 = -1;
  prev: [number, number, number, number] | null = null;

  constructor(public canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
  }
  resize(W: number, H: number) {
    this.canvas.width = W; this.canvas.height = H; this.W = W; this.H = H;
    const n = W * H;
    this.w = new Float32Array(n); this.r = new Float32Array(n); this.g = new Float32Array(n); this.b = new Float32Array(n);
    this.img = this.ctx.createImageData(W, H); this.px = new Uint32Array(this.img.data.buffer);
    this.prev = null; this.x0 = W; this.y0 = H; this.x1 = -1; this.y1 = -1;
  }
  private grow(ax: number, ay: number, bx: number, by: number) {
    if (ax < this.x0) this.x0 = ax; if (ay < this.y0) this.y0 = ay;
    if (bx > this.x1) this.x1 = bx; if (by > this.y1) this.y1 = by;
  }
  splat(sx: number, sy: number, a: number, c: RGB | number[]) {
    const fx = sx - 0.5, fy = sy - 0.5, ix = Math.floor(fx), iy = Math.floor(fy), W = this.W;
    if (ix < 0 || iy < 0 || ix >= W - 1 || iy >= this.H - 1) return;
    const tx = fx - ix, ty = fy - iy, p = iy * W + ix;
    const ws = [a * (1 - tx) * (1 - ty), a * tx * (1 - ty), a * (1 - tx) * ty, a * tx * ty], ps = [p, p + 1, p + W, p + W + 1];
    for (let j = 0; j < 4; j++) {
      const q = ps[j], wj = ws[j];
      this.w[q] += wj; this.r[q] += wj * c[0]; this.g[q] += wj * c[1]; this.b[q] += wj * c[2];
    }
    this.grow(ix, iy, ix + 1, iy + 1);
  }
  disc(sx: number, sy: number, rad: number, a: number, c: RGB | number[]) {
    if (rad < 0.75) { this.splat(sx, sy, a * Math.max(Math.PI * rad * rad, 0.5), c); return; }
    const W = this.W;
    const ax = Math.max(0, Math.floor(sx - rad - 1)), bx = Math.min(W - 1, Math.ceil(sx + rad + 1));
    const ay = Math.max(0, Math.floor(sy - rad - 1)), by = Math.min(this.H - 1, Math.ceil(sy + rad + 1));
    if (ax > bx || ay > by) return;
    for (let y = ay; y <= by; y++) {
      const dy = y + 0.5 - sy;
      let p = y * W + ax;
      for (let x = ax; x <= bx; x++, p++) {
        const dx = x + 0.5 - sx;
        let cov = rad + 0.5 - Math.sqrt(dx * dx + dy * dy);
        if (cov <= 0) continue;
        if (cov > 1) cov = 1;
        const wv = a * cov;
        this.w[p] += wv; this.r[p] += wv * c[0]; this.g[p] += wv * c[1]; this.b[p] += wv * c[2];
      }
    }
    this.grow(ax, ay, bx, by);
  }
  ring(sx: number, sy: number, rad: number, lw: number, a: number, c: RGB) {
    const W = this.W;
    const ax = Math.max(0, Math.floor(sx - rad - 1)), bx = Math.min(W - 1, Math.ceil(sx + rad + 1));
    const ay = Math.max(0, Math.floor(sy - rad - 1)), by = Math.min(this.H - 1, Math.ceil(sy + rad + 1));
    for (let y = ay; y <= by; y++) {
      const dy = y + 0.5 - sy;
      let p = y * W + ax;
      for (let x = ax; x <= bx; x++, p++) {
        const dx = x + 0.5 - sx, d = Math.sqrt(dx * dx + dy * dy);
        const cov = clamp01(rad + 0.5 - d) * clamp01(d - (rad - lw) + 0.5);
        if (cov <= 0) continue;
        const wv = a * cov * 4;
        this.w[p] += wv; this.r[p] += wv * c[0]; this.g[p] += wv * c[1]; this.b[p] += wv * c[2];
      }
    }
    this.grow(ax, ay, bx, by);
  }
  commit() {
    const px = this.px, W = this.W, has = this.x1 >= this.x0;
    if (this.prev) { const [a0, b0, a1, b1] = this.prev; for (let y = b0; y <= b1; y++) px.fill(0, y * W + a0, y * W + a1 + 1); }
    const Wt = this.w, R = this.r, G = this.g, B = this.b;
    if (has) {
      for (let y = this.y0; y <= this.y1; y++) {
        let p = y * W + this.x0;
        for (let x = this.x0; x <= this.x1; x++, p++) {
          const w = Wt[p];
          if (w > 0) {
            const inv = 1 / w, al = LUT[w >= 15.99 ? 2047 : (w * 128) | 0];
            px[p] = ((al << 24) | ((B[p] * inv) << 16) | ((G[p] * inv) << 8) | (R[p] * inv)) >>> 0;
            Wt[p] = 0; R[p] = 0; G[p] = 0; B[p] = 0;
          }
        }
      }
    }
    const cur: [number, number, number, number] | null = has ? [this.x0, this.y0, this.x1, this.y1] : null, pr = this.prev;
    if (this.img && (cur || pr)) {
      const u = cur && pr ? [Math.min(cur[0], pr[0]), Math.min(cur[1], pr[1]), Math.max(cur[2], pr[2]), Math.max(cur[3], pr[3])] : (cur || pr)!;
      this.ctx.putImageData(this.img, 0, 0, u[0], u[1], u[2] - u[0] + 1, u[3] - u[1] + 1);
    }
    this.prev = cur; this.x0 = W; this.y0 = this.H; this.x1 = -1; this.y1 = -1;
  }
}

interface Anim { from: number; to: number; t0: number; ms: number; set: (v: number) => void; ease: (t: number) => number }

export class DotWorld {
  readonly d: MapData;
  readonly n: number;
  readonly M: number;
  private base: Layer;
  private top: Layer;
  private dpr = 1;
  cssW = 0;
  cssH = 0;
  cam: Camera = { x: 330, y: 312, z: 1 };
  view: View = "map";
  measure = 3;
  hideNeutral = false;
  showBase = true;
  selected = -1;
  private baseA = 1;
  private dim = 1;
  focus = -1;                          // district whose dots stay dark
  visible = 0;                         // personas on screen after the last full base draw
  private cls: Uint8Array;            // m × n: 0 favour, 1 neutral, 2 against (one draw per person, same for every measure)
  private sortedPos: Map<string, Float32Array> = new Map();
  // transition between two panel states: 10 copies per person (copy j = measure j, only used by the waffles)
  private fromX: Float32Array; private fromY: Float32Array; private fromA: Float32Array; private fromR: Float32Array;
  private fromC: Float32Array;
  private lastX: Float32Array; private lastY: Float32Array; private lastA: Float32Array; private lastR: Float32Array;
  private lastC: Float32Array;
  private trans = 1;                   // 0..1 progress of the current panel transition
  private stagger: Float32Array;
  private anims: Anim[] = [];
  private raf = 0;
  private dirtyBase = true;
  private dirtyTop = true;
  private coarse = false;              // fewer base dots while the user drags or zooms
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  labels: Label[] = [];
  onFrame: (() => void) | null = null;

  constructor(baseCanvas: HTMLCanvasElement, topCanvas: HTMLCanvasElement, data: MapData) {
    this.d = data; this.n = data.meta.panel.n; this.M = data.meta.panel.m;
    this.base = new Layer(baseCanvas); this.top = new Layer(topCanvas);
    const n = this.n, M = this.M, N10 = n * M;
    this.cls = new Uint8Array(M * n);
    for (let k = 0; k < n; k++) {
      const u = hash(k, 91);
      for (let m = 0; m < M; m++) {
        const f = data.fav[m * n + k] / 100, o = data.opp[m * n + k] / 100;
        this.cls[m * n + k] = u < f ? 0 : u >= 1 - o ? 2 : 1;
      }
    }
    this.stagger = new Float32Array(n);
    for (let k = 0; k < n; k++) this.stagger[k] = hash(k, 23);
    this.fromX = new Float32Array(N10); this.fromY = new Float32Array(N10); this.fromA = new Float32Array(N10);
    this.fromR = new Float32Array(N10); this.fromC = new Float32Array(N10 * 3);
    this.lastX = new Float32Array(N10); this.lastY = new Float32Array(N10); this.lastA = new Float32Array(N10);
    this.lastR = new Float32Array(N10); this.lastC = new Float32Array(N10 * 3);
  }

  // ------------------------------------------------------------------ size and camera
  resize(cssW: number, cssH: number, dpr: number) {
    this.cssW = cssW; this.cssH = cssH; this.dpr = dpr;
    this.base.resize(Math.round(cssW * dpr), Math.round(cssH * dpr));
    this.top.resize(Math.round(cssW * dpr), Math.round(cssH * dpr));
    this.sortedPos.clear(); this.blockCache.clear();
    this.dirtyBase = this.dirtyTop = true;
    this.relabel();
    this.request();
  }
  // the mainland and Jeju fill the box; the far islands (백령도, 울릉도, 독도) are a pan away
  fitCamera(): Camera {
    const x0 = 112, x1 = 478, y0 = 8, y1 = 630;
    const z = Math.min((this.cssW - 24) / (x1 - x0), (this.cssH - 24) / (y1 - y0));
    return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, z };
  }
  districtCamera(j: number): Camera {
    const dd = this.d.meta.districts[j];
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (let i = dd.s; i < dd.s + dd.n; i += Math.max(1, Math.floor(dd.n / 400))) {
      const x = this.d.x[i], y = this.d.y[i];
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    const span = Math.max(x1 - x0, y1 - y0, 6);
    return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: Math.min(90, Math.min(this.cssW, this.cssH) * 0.8 / span) };
  }
  screen(wx: number, wy: number): [number, number] {
    return [(wx - this.cam.x) * this.cam.z + this.cssW / 2, (wy - this.cam.y) * this.cam.z + this.cssH / 2];
  }
  setCamera(c: Camera) {
    this.cam = { ...c };
    this.dirtyBase = this.dirtyTop = true;
    this.request();
  }
  flyTo(g: Camera, ms = 1200) {
    const f = { ...this.cam };
    this.animate(0, 1, ms, (p) => {
      const lz0 = Math.log(f.z), lz1 = Math.log(g.z), z = Math.exp(lz0 + (lz1 - lz0) * p);
      let x: number, y: number;
      if (Math.abs(lz1 - lz0) < 1e-6) { x = f.x + (g.x - f.x) * p; y = f.y + (g.y - f.y) * p; }
      else if (lz0 > lz1) { x = f.x - ((f.x - g.x) * g.z * p) / z; y = f.y - ((f.y - g.y) * g.z * p) / z; }
      else { x = g.x - ((g.x - f.x) * f.z * (1 - p)) / z; y = g.y - ((g.y - f.y) * f.z * (1 - p)) / z; }
      this.cam = { x, y, z };
      this.dirtyBase = this.dirtyTop = true;
    }, easeInOut, "cam");
  }
  // drag/zoom by the user: coarse base dots until the hand stops
  pan(dx: number, dy: number) {
    this.stop("cam");
    this.cam = { ...this.cam, x: this.cam.x - dx / this.cam.z, y: this.cam.y - dy / this.cam.z };
    this.touch();
  }
  zoomAt(px: number, py: number, factor: number) {
    this.stop("cam");
    const z = Math.min(400, Math.max(this.fitCamera().z * 0.7, this.cam.z * factor));
    const wx = (px - this.cssW / 2) / this.cam.z + this.cam.x, wy = (py - this.cssH / 2) / this.cam.z + this.cam.y;
    this.cam = { x: wx - (px - this.cssW / 2) / z, y: wy - (py - this.cssH / 2) / z, z };
    this.touch();
  }
  private touch() {
    this.coarse = true;
    this.dirtyBase = this.dirtyTop = true;
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => { this.coarse = false; this.dirtyBase = true; this.request(); }, 160);
    this.request();
  }

  // ------------------------------------------------------------------ what the panel shows
  setMeasure(m: number) {
    if (m === this.measure) return;
    this.beginTransition();
    this.measure = m;
    this.startTransition(this.view === "map" ? 1300 : 1100);
  }
  setView(v: View) {
    if (v === this.view) return;
    this.beginTransition();
    this.view = v;
    this.animate(this.baseA, v === "map" ? 1 : 0.06, 700, (x) => { this.baseA = x; this.dirtyBase = true; }, easeInOut, "baseA");
    this.startTransition(v === "waffle" || this.lastWasWaffle ? 1800 : 1300);
    this.lastWasWaffle = v === "waffle";
  }
  private lastWasWaffle = false;
  setHideNeutral(h: boolean) {
    if (h === this.hideNeutral) return;
    this.beginTransition();
    this.hideNeutral = h;
    this.startTransition(1000);
  }
  setShowBase(s: boolean) {
    this.showBase = s;
    this.dirtyBase = true;
    this.request();
  }
  select(k: number) {
    this.selected = k;
    this.dirtyTop = true;
    this.request();
  }
  classOf(m: number, k: number) { return this.cls[m * this.n + k]; }

  private beginTransition() {
    // freeze what is on screen now as the starting point
    this.fromX.set(this.lastX); this.fromY.set(this.lastY); this.fromA.set(this.lastA);
    this.fromR.set(this.lastR); this.fromC.set(this.lastC);
  }
  private startTransition(ms: number) {
    this.trans = 0;
    this.relabel();
    this.animate(0, 1, ms, (x) => { this.trans = x; this.dirtyTop = true; }, (t) => t, "trans");
  }

  // ------------------------------------------------------------------ layouts
  private members(): { name: string; sel: (k: number) => boolean; a?: number }[] {
    const d = this.d;
    if (this.view === "tenure") {
      return [
        { name: "집 2채 이상", sel: (k) => tenureOf(d, k) === 0 && multiOf(d, k) },
        { name: "1주택", sel: (k) => tenureOf(d, k) === 0 && !multiOf(d, k) },
        { name: "전세", sel: (k) => tenureOf(d, k) === 1 },
        { name: "월세", sel: (k) => tenureOf(d, k) === 2 },
        { name: "기타", sel: (k) => tenureOf(d, k) === 3 },
      ];
    }
    return [
      { name: "서울", sel: (k) => d.province[k] === "서울" },
      { name: "경기·인천", sel: (k) => d.province[k] === "경기" || d.province[k] === "인천" },
      { name: "비수도권", sel: (k) => !CAPITAL.has(d.province[k]) },
    ];
  }
  // bars of 100 columns, sorted favour | neutral | against for the current measure (screen CSS px)
  private blockCache = new Map<string, { pos: Float32Array; labels: Label[]; dot: number }>();
  private blocks(): { pos: Float32Array; labels: Label[]; dot: number } {
    const key = `${this.view}:${this.measure}:${this.hideNeutral}:${this.cssW}x${this.cssH}`;
    const hit = this.blockCache.get(key);
    if (hit) return hit;
    const groups = this.members(), n = this.n, m = this.measure;
    const lists = groups.map((g) => {
      const byCls: number[][] = [[], [], []];
      for (let k = 0; k < n; k++) if (g.sel(k)) byCls[this.cls[m * n + k]].push(k);
      return byCls;
    });
    const rowsOf = (b: number[][]) => Math.max(1, Math.ceil((this.hideNeutral ? b[0].length + b[2].length : b[0].length + b[1].length + b[2].length) / 100));
    const narrow = this.cssW < 640;
    const totalRows = lists.reduce((a, b) => a + rowsOf(b), 0);
    // wide: names on the left, numbers on the right of each bar. narrow: one line above each bar, edge to edge.
    const labelW = narrow ? 0 : Math.min(130, this.cssW * 0.18), valueW = narrow ? 0 : Math.min(150, this.cssW * 0.2);
    const top = narrow ? 10 : 30, gap = narrow ? 10 : 30, lineH = narrow ? 20 : 0, bottom = narrow ? 10 : 20;
    const room = this.cssH - top - bottom - gap * (groups.length - 1) - lineH * groups.length;
    const pitch = Math.max(1, Math.min(5, (this.cssW - labelW - valueW - (narrow ? 24 : 48)) / 100, room / totalRows));
    const x0 = narrow ? (this.cssW - 100 * pitch) / 2 : labelW + 24 + (this.cssW - labelW - valueW - 48 - 100 * pitch) / 2;
    const pos = new Float32Array(2 * n).fill(NaN);
    const labels: Label[] = [];
    let y = top + Math.max(0, (room - totalRows * pitch) / 2);
    groups.forEach((g, gi) => {
      const b = lists[gi];
      const order = this.hideNeutral ? [...b[0], ...b[2]] : [...b[0], ...b[1], ...b[2]];
      const rows = rowsOf(b);
      const members = [...b[0], ...b[1], ...b[2]];
      // numbers are mean probabilities (as on the series page); the dots are one draw each, so they can differ a little
      let f = 0, o = 0;
      for (const k of members) { f += this.d.fav[m * n + k]; o += this.d.opp[m * n + k]; }
      const pf = members.length ? f / members.length : 0, po = members.length ? o / members.length : 0;
      const decidedShare = Math.round((100 * pf) / Math.max(1, pf + po));
      const sub = `${members.length.toLocaleString()}명`;
      if (narrow) {
        labels.push({ x: 12, y, text: g.name, sub, align: "left" });
        labels.push({ x: this.cssW - 12, y, text: this.hideNeutral ? `찬성 ${decidedShare}%` : `찬성 ${Math.round(pf)}%`,
          sub: this.hideNeutral ? "정한 사람 중" : `반대 ${Math.round(po)}%`, align: "right", tone: "fav" });
        y += lineH;
      }
      order.forEach((k, j) => { pos[2 * k] = x0 + (Math.floor(j / rows) + 0.5) * pitch; pos[2 * k + 1] = y + ((j % rows) + 0.5) * pitch; });
      const h = rows * pitch;
      if (!narrow) {
        labels.push({ x: x0 - 14, y: y + h / 2, text: g.name, sub, align: "right" });
        labels.push({ x: x0 + 100 * pitch + 14, y: y + h / 2, text: this.hideNeutral ? `찬성 쪽 ${decidedShare}%` : `찬성 쪽 ${Math.round(pf)}%`,
          sub: this.hideNeutral ? "찬반을 정한 사람 중" : `반대 쪽 ${Math.round(po)}%`, align: "left", tone: "fav" });
      }
      y += h + gap;
    });
    const out = { pos, labels, dot: Math.max(0.6, pitch * 0.4) };
    this.blockCache.set(key, out);
    return out;
  }
  private waffleGeom() {
    const M = this.M, cols = 5, rows = Math.ceil(M / cols), narrow = this.cssW < 640;
    const labelH = narrow ? 34 : 30, gapX = narrow ? 8 : 18, gapY = narrow ? 12 : 16;
    const size = Math.min((this.cssW - 24 - gapX * (cols - 1)) / cols, (this.cssH - 16 - rows * labelH - gapY * (rows - 1)) / rows);
    const pitch = size / 100;
    const x0 = (this.cssW - (cols * size + (cols - 1) * gapX)) / 2;
    const y0 = (this.cssH - (rows * (size + labelH) + (rows - 1) * gapY)) / 2 + labelH;
    const origin = (m: number) => [x0 + (m % cols) * (size + gapX), y0 + Math.floor(m / cols) * (size + labelH + gapY)] as const;
    return { pitch, size, origin, labelH };
  }
  private waffles(): Float32Array {
    const key = `waffle`;
    const cached = this.sortedPos.get(key);
    if (cached) return cached;
    const n = this.n, M = this.M, { pitch, origin } = this.waffleGeom();
    const pos = new Float32Array(2 * n * M);
    for (let m = 0; m < M; m++) {
      const byCls: number[][] = [[], [], []];
      for (let k = 0; k < n; k++) byCls[this.cls[m * n + k]].push(k);
      const [ox, oy] = origin(m), order = [...byCls[0], ...byCls[1], ...byCls[2]], rows = Math.ceil(n / 100);
      order.forEach((k, j) => {
        pos[2 * (m * n + k)] = ox + (Math.floor(j / rows) + 0.5) * pitch;
        pos[2 * (m * n + k) + 1] = oy + ((j % rows) + 0.5) * pitch;
      });
    }
    this.sortedPos.set(key, pos);
    return pos;
  }
  private relabel() {
    if (!this.cssW) return;
    if (this.view === "tenure" || this.view === "region") this.labels = this.blocks().labels;
    else if (this.view === "waffle") {
      const { origin, size } = this.waffleGeom();
      this.labels = this.d.meta.measures.map((mm, m) => {
        const [ox, oy] = origin(m);
        return { x: ox + size / 2, y: oy - (this.cssW < 640 ? 18 : 15), text: mm.short, value: `${Math.round(mm.favor * 100)}%`, align: "center" as const, tone: m === this.measure ? "fav" as const : undefined };
      });
    } else this.labels = [];
  }

  // ------------------------------------------------------------------ drawing
  private drawBase() {
    const L = this.base, d = this.d, N = d.meta.n_dots, dpr = this.dpr;
    const a0 = this.showBase ? this.baseA : 0;
    if (a0 <= 0.003) { L.commit(); return; }
    const z = this.cam.z * dpr, cx = this.cam.x, cy = this.cam.y, hw = L.W / 2, hh = L.H / 2;
    let r = 0.07 * this.cam.z * dpr;
    r = Math.min(Math.max(r, 0.42 * dpr), 2.1 * dpr);
    const sub = r < 0.75, area = Math.max(Math.PI * r * r, 0.5);
    const pad = (r + 2) / z, wx0 = cx - hw / z - pad, wx1 = cx + hw / z + pad, wy0 = cy - hh / z - pad, wy1 = cy + hh / z + pad;
    const dim = this.dim, col: number[] = [INK[0] + (DIM[0] - INK[0]) * dim, INK[1] + (DIM[1] - INK[1]) * dim, INK[2] + (DIM[2] - INK[2]) * dim];
    const aScale = a0 * (1 - 0.45 * dim);
    const step = this.coarse ? 3 : 1, wgt = step;
    const X = d.x, Y = d.y, dist = d.dist, focus = this.focus;
    let seen = 0;
    for (let i = 0; i < N; i += step) {
      const x = X[i], y = Y[i];
      if (x < wx0 || x > wx1 || y < wy0 || y > wy1) continue;
      const sx = (x - cx) * z + hw, sy = (y - cy) * z + hh;
      if (sx >= 0 && sx < L.W && sy >= 0 && sy < L.H) seen++;
      const f = focus >= 0 && dist[i] === focus;
      const c = f ? FOCUS : col, a = f ? a0 * 0.75 : aScale;
      if (sub) L.splat(sx, sy, a * area * wgt, c);
      else L.disc(sx, sy, r, a * (step > 1 ? Math.min(1, 0.6 * wgt) : 1), c);
    }
    if (step === 1) this.visible = seen;
    L.commit();
  }

  // Every person has M copies (copy m = measure m). Outside the waffle view only the copy of the current measure is
  // visible; the others ride along at the same spot with opacity 0, so a transition into the waffles starts from the
  // person's dot and a transition out of them flies back to it.
  private drawTop() {
    const L = this.top, n = this.n, M = this.M, dpr = this.dpr, cur = this.measure, d = this.d;
    const z = this.cam.z, hw = this.cssW / 2, hh = this.cssH / 2;
    const mapR = Math.min(4.5, Math.max(1.1, 0.11 * z));
    const bl = this.view === "tenure" || this.view === "region" ? this.blocks() : null;
    const waffle = this.view === "waffle" ? this.waffles() : null;
    const wR = waffle ? this.waffleGeom().pitch * 0.42 : 0;
    const t = this.trans, animating = t < 1;
    const order = [cur, ...Array.from({ length: M }, (_, m) => m).filter((m) => m !== cur)];
    for (let k = 0; k < n; k++) {
      let px = NaN, py = NaN, pr = 0;                   // where the current copy is drawn
      const st = this.stagger[k];
      for (const m of order) {
        const q = m * n + k, f3 = 3 * q;
        let tx: number, ty: number, tr: number, ta: number, tc: number;
        if (waffle) { tx = waffle[2 * q]; ty = waffle[2 * q + 1]; tr = wR; ta = 1; tc = this.cls[q]; }
        else if (bl) { tx = bl.pos[2 * k]; ty = bl.pos[2 * k + 1]; tr = bl.dot; ta = m === cur && tx === tx ? 1 : 0; tc = this.cls[cur * n + k]; }
        else {
          const i = d.idx[k];
          tx = (d.x[i] - this.cam.x) * z + hw; ty = (d.y[i] - this.cam.y) * z + hh; tr = mapR; ta = m === cur ? 1 : 0;
          tc = this.cls[cur * n + k];
        }
        const c = CLS[tc];
        let x = tx, y = ty, rad = tr, a = ta, cr = c[0], cg = c[1], cb = c[2];
        if (animating) {
          const pt = smooth(clamp01((t - st * 0.35 - (waffle ? m * 0.02 : 0)) / 0.6));
          const fx = this.fromX[q], fy = this.fromY[q], fa = this.fromA[q];
          if (x !== x) { x = fx; y = fy; }                          // no place in the new layout: fade where it was
          else if (fx === fx) { x = fx + (x - fx) * pt; y = fy + (y - fy) * pt; }
          rad = this.fromR[q] + (tr - this.fromR[q]) * pt;
          a = fa + (ta - fa) * pt;
          cr = this.fromC[f3] + (cr - this.fromC[f3]) * pt; cg = this.fromC[f3 + 1] + (cg - this.fromC[f3 + 1]) * pt;
          cb = this.fromC[f3 + 2] + (cb - this.fromC[f3 + 2]) * pt;
        } else if (!waffle && m !== cur) {
          x = px; y = py; rad = pr; a = 0;                           // hidden copy rides with the visible one
          const c3 = 3 * (cur * n + k);
          cr = this.lastC[c3]; cg = this.lastC[c3 + 1]; cb = this.lastC[c3 + 2];
        }
        if (m === cur) { px = x; py = y; pr = rad; }
        this.lastX[q] = x; this.lastY[q] = y; this.lastA[q] = a; this.lastR[q] = rad;
        this.lastC[f3] = cr; this.lastC[f3 + 1] = cg; this.lastC[f3 + 2] = cb;
        if (a <= 0.003 || x !== x || x < -8 || x > this.cssW + 8 || y < -8 || y > this.cssH + 8) continue;
        L.disc(x * dpr, y * dpr, rad * dpr, a * 1.5, [cr, cg, cb]);
      }
    }
    const sel = this.selected;
    if (sel >= 0) {
      const q = cur * n + sel, x = this.lastX[q], y = this.lastY[q];
      if (x === x && this.lastA[q] > 0.3) L.ring(x * dpr, y * dpr, Math.max(7, this.lastR[q] + 5) * dpr, 2 * dpr, 1, INK);
    }
    L.commit();
  }

  // ------------------------------------------------------------------ picking
  pick(px: number, py: number): number {
    const n = this.n, m = this.measure, r = 9;
    let best = -1, bd = r * r;
    for (let k = 0; k < n; k++) {
      const q = m * n + k;
      if (this.lastA[q] < 0.5) continue;
      const dx = this.lastX[q] - px, dy = this.lastY[q] - py, dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = k; }
    }
    return best;
  }
  districtAt(px: number, py: number): number {
    if (this.view !== "map") return -1;
    const d = this.d, N = d.meta.n_dots, z = this.cam.z;
    const wx = (px - this.cssW / 2) / z + this.cam.x, wy = (py - this.cssH / 2) / z + this.cam.y;
    const r = 10 / z;
    let best = -1, bd = r * r;
    for (let i = 0; i < N; i++) {
      const dx = d.x[i] - wx; if (dx > r || dx < -r) continue;
      const dy = d.y[i] - wy; if (dy > r || dy < -r) continue;
      const dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = i; }
    }
    return best < 0 ? -1 : d.dist[best];
  }

  // ------------------------------------------------------------------ loop
  private animate(from: number, to: number, ms: number, set: (v: number) => void, ease: (t: number) => number, tag: string) {
    this.stop(tag);
    const a: Anim & { tag?: string } = { from, to, t0: performance.now(), ms, set, ease };
    (a as { tag?: string }).tag = tag;
    this.anims.push(a);
    set(from);
    this.request();
  }
  private stop(tag: string) {
    this.anims = this.anims.filter((a) => (a as { tag?: string }).tag !== tag);
  }
  setDim(v: number) { this.dim = v; this.dirtyBase = true; this.request(); }
  setFocus(j: number) { this.focus = j; this.dirtyBase = true; this.request(); }
  request() {
    if (!this.raf && typeof window !== "undefined") this.raf = requestAnimationFrame(() => this.frame());
  }
  private frame() {
    this.raf = 0;
    const now = performance.now();
    for (const a of this.anims) {
      const t = clamp01((now - a.t0) / a.ms);
      a.set(a.from + (a.to - a.from) * a.ease(t));
    }
    this.anims = this.anims.filter((a) => now - a.t0 < a.ms);
    if (this.dirtyBase) { this.drawBase(); this.dirtyBase = false; }
    if (this.dirtyTop || this.trans < 1) { this.drawTop(); this.dirtyTop = false; }
    this.onFrame?.();
    if (this.anims.length) this.request();
  }
  destroy() {
    if (this.raf) cancelAnimationFrame(this.raf);
    if (this.idleTimer) clearTimeout(this.idleTimer);
  }
}
