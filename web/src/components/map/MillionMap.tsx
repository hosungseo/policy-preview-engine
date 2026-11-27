"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { stripPersonaName } from "@/lib/format";
import { loadMap, loadPerson, multiOf, shares, tenureOf, type MapData, type Person, type Shares } from "@/lib/peopleMap";
import { DotWorld, type Label, type View } from "./dotWorld";
import "./map.css";

const BASE = "/series/housing-map";
const VIEWS: { key: View; label: string }[] = [
  { key: "map", label: "지도" },
  { key: "tenure", label: "점유 형태" },
  { key: "region", label: "서울·수도권·비수도권" },
  { key: "waffle", label: "대책 10건" },
];
const pct = (v: number) => `${Math.round(v * 100)}%`;
const SEOUL = { x: 221, y: 131, z: 26 };

function ShareBar({ s, small }: { s: Shares; small?: boolean }) {
  return (
    <div className={`pp-mm-share${small ? " is-small" : ""}`} aria-label={`찬성 쪽 ${pct(s.favor)}, 중립 ${pct(s.neutral)}, 반대 쪽 ${pct(s.oppose)}`}>
      <div className="pp-mm-share-bar">
        <i style={{ width: pct(s.favor), background: "#256ef4" }} />
        <i style={{ width: pct(s.neutral), background: "#b1b8be" }} />
        <i style={{ width: pct(s.oppose), background: "#d63d4a" }} />
      </div>
      {!small && (
        <div className="pp-mm-share-nums">
          <span className="is-fav">찬성 쪽 {pct(s.favor)}</span><span>중립 {pct(s.neutral)}</span><span className="is-opp">반대 쪽 {pct(s.oppose)}</span>
        </div>
      )}
    </div>
  );
}

export default function MillionMap() {
  const wrap = useRef<HTMLDivElement>(null);
  const baseCv = useRef<HTMLCanvasElement>(null);
  const topCv = useRef<HTMLCanvasElement>(null);
  const counter = useRef<HTMLSpanElement>(null);
  const world = useRef<DotWorld | null>(null);
  const [data, setData] = useState<MapData | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [measure, setMeasure] = useState(3);
  const [view, setView] = useState<View>("map");
  const [hideNeutral, setHideNeutral] = useState(false);
  const [showBase, setShowBase] = useState(true);
  const [labels, setLabels] = useState<Label[]>([]);
  const [picked, setPicked] = useState<{ k: number; p: Person | null } | null>(null);
  const [district, setDistrict] = useState(-1);
  const [hint, setHint] = useState(false);

  useEffect(() => {
    if (!hint) return;
    const t = setTimeout(() => setHint(false), 2600);
    return () => clearTimeout(t);
  }, [hint]);

  useEffect(() => {
    let alive = true;
    loadMap(BASE, (s) => alive && setProgress(s)).then((d) => alive && setData(d)).catch((e) => alive && setError(String(e)));
    return () => { alive = false; };
  }, []);

  // the engine, sized to its box
  useEffect(() => {
    if (!data || !baseCv.current || !topCv.current || !wrap.current) return;
    const w = new DotWorld(baseCv.current, topCv.current, data);
    world.current = w;
    const box = wrap.current;
    let first = true;
    const fit = () => {
      const r = box.getBoundingClientRect();
      if (r.width < 10 || r.height < 10) return;
      const was = w.cssW ? w.fitCamera().z : 0;
      w.resize(r.width, r.height, Math.min(window.devicePixelRatio || 1, 1.5));
      if (first || Math.abs(w.cam.z - was) < 1e-6) w.setCamera(w.fitCamera());
      first = false;
      setLabels([...w.labels]);
    };
    fit();
    w.onFrame = () => {
      if (counter.current) counter.current.textContent = w.visible.toLocaleString("en-US");
    };
    const ro = new ResizeObserver(fit);
    ro.observe(box);
    return () => { ro.disconnect(); w.destroy(); world.current = null; };
  }, [data]);

  // pointer: mouse drag pans; touch pans and pinches with two fingers (one finger keeps scrolling the page)
  useEffect(() => {
    const el = topCv.current;
    const w = () => world.current;
    if (!el || !data) return;
    const pts = new Map<number, { x: number; y: number }>();
    let downAt = 0, moved = 0, last: { x: number; y: number } | null = null, lastPinch = 0, fingers = 0, hints = 0;
    const local = (e: PointerEvent) => { const r = el.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    const onDown = (e: PointerEvent) => {
      pts.set(e.pointerId, local(e));
      fingers = Math.max(fingers, pts.size);
      el.setPointerCapture(e.pointerId);
      downAt = performance.now(); moved = 0; last = local(e); lastPinch = 0;
    };
    const onMove = (e: PointerEvent) => {
      if (!pts.has(e.pointerId)) return;
      const p = local(e);
      pts.set(e.pointerId, p);
      const world_ = w();
      if (!world_ || world_.view !== "map") return;
      if (pts.size >= 2) {
        const [a, b] = [...pts.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y), mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        if (lastPinch) world_.zoomAt(mid.x, mid.y, dist / lastPinch);
        if (last) world_.pan(mid.x - last.x, mid.y - last.y);
        lastPinch = dist; last = mid; moved += 10;
      } else if (e.pointerType !== "touch" && last) {
        world_.pan(p.x - last.x, p.y - last.y);
        moved += Math.abs(p.x - last.x) + Math.abs(p.y - last.y);
        last = p;
      }
    };
    const onUp = (e: PointerEvent) => {
      const p = local(e);
      pts.delete(e.pointerId);
      if (pts.size) { last = [...pts.values()][0]; lastPinch = 0; return; }
      fingers = 0;
      const world_ = w();
      if (!world_ || moved > 6 || performance.now() - downAt > 500) return;
      const k = world_.pick(p.x, p.y);
      if (k >= 0) {
        world_.select(k);
        setPicked({ k, p: null });
        loadPerson(BASE, data, k).then((person) => setPicked((cur) => (cur && cur.k === k ? { k, p: person } : cur)));
        return;
      }
      const j = world_.districtAt(p.x, p.y);
      if (j >= 0) { world_.setFocus(j); setDistrict(j); world_.select(-1); setPicked(null); }
    };
    // the browser took the gesture over (page scroll): forget it, never treat it as a tap. A one-finger drag that
    // scrolled the page instead of the map gets the two-finger hint, a few times per visit.
    const onCancel = (e: PointerEvent) => {
      pts.delete(e.pointerId);
      if (!pts.size) {
        if (e.pointerType === "touch" && fingers === 1 && hints < 3 && w()?.view === "map") { hints++; setHint(true); }
        fingers = 0;
      }
      moved = 99; last = null; lastPinch = 0;
    };
    const onWheel = (e: WheelEvent) => {
      const world_ = w();
      if (!world_ || world_.view !== "map") return;
      e.preventDefault();
      const p = { x: e.offsetX, y: e.offsetY };
      world_.zoomAt(p.x, p.y, Math.exp(-e.deltaY * 0.0016));
    };
    const onDbl = (e: MouseEvent) => {
      const world_ = w();
      if (!world_ || world_.view !== "map") return;
      const c = world_.cam, z = Math.min(400, c.z * 2.2);
      world_.flyTo({ x: (e.offsetX - world_.cssW / 2) / c.z + c.x, y: (e.offsetY - world_.cssH / 2) / c.z + c.y, z }, 700);
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onCancel);
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("dblclick", onDbl);
    return () => {
      el.removeEventListener("pointerdown", onDown); el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp); el.removeEventListener("pointercancel", onCancel);
      el.removeEventListener("wheel", onWheel); el.removeEventListener("dblclick", onDbl);
    };
  }, [data]);

  const act = useCallback((f: (w: DotWorld) => void) => {
    const w = world.current;
    if (!w) return;
    f(w);
    setLabels([...w.labels]);
  }, []);
  const chooseMeasure = (m: number) => { setMeasure(m); act((w) => w.setMeasure(m)); };
  const chooseView = (v: View) => { setView(v); act((w) => w.setView(v)); if (v !== "map") setHint(false); };
  const chooseNeutral = (h: boolean) => { setHideNeutral(h); act((w) => w.setHideNeutral(h)); };
  const goDistrict = (j: number) => {
    setDistrict(j);
    act((w) => { w.setFocus(j); if (j >= 0) { if (w.view !== "map") { setView("map"); w.setView("map"); } w.flyTo(w.districtCamera(j), 1300); } });
  };
  const zoom = (f: number) => act((w) => w.flyTo({ ...w.cam, z: Math.min(400, Math.max(w.fitCamera().z * 0.7, w.cam.z * f)) }, 450));

  const meta = data?.meta;
  const m = meta?.measures[measure];
  const national = useMemo(() => (data ? shares(data, measure, () => true) : null), [data, measure]);
  const local = useMemo(() => (data && district >= 0 ? shares(data, measure, (k) => data.dist[data.idx[k]] === district) : null), [data, measure, district]);
  const mine = useMemo(() => {
    if (!data || !picked) return null;
    const n = data.meta.panel.n;
    return data.meta.measures.map((mm, j) => {
      const f = data.fav[j * n + picked.k] / 100, o = data.opp[j * n + picked.k] / 100;
      return { short: mm.short, s: { n: 1, favor: f, oppose: o, neutral: Math.max(0, 1 - f - o) } };
    });
  }, [data, picked]);
  const tenureText = (k: number) => {
    if (!data || !meta) return "";
    const t = tenureOf(data, k);
    return `${meta.tenure_labels[t]}${t === 0 && multiOf(data, k) ? " · 집 2채 이상" : ""}`;
  };
  const provinces = useMemo(() => {
    if (!meta) return [] as { p: string; items: { j: number; name: string }[] }[];
    const out: { p: string; items: { j: number; name: string }[] }[] = [];
    meta.districts.forEach((dd, j) => {
      const [p] = dd.name.split(" ");
      const g = out.find((x) => x.p === p) ?? (out.push({ p, items: [] }), out[out.length - 1]);
      g.items.push({ j, name: dd.name });
    });
    return out;
  }, [meta]);

  return (
    <div className="pp-mm">
      <div className="pp-mm-bar" role="toolbar" aria-label="대책 선택">
        {(meta?.measures ?? []).map((mm, j) => (
          <button key={mm.id} type="button" className={`pp-mm-chip${j === measure ? " is-on" : ""}`} aria-pressed={j === measure}
            onClick={() => chooseMeasure(j)} title={mm.title}>{mm.short}</button>
        ))}
      </div>
      <div className="pp-mm-bar is-views" role="toolbar" aria-label="보기">
        <div className="pp-mm-seg">
          {VIEWS.map((v) => (
            <button key={v.key} type="button" className={view === v.key ? "is-on" : ""} aria-pressed={view === v.key}
              onClick={() => chooseView(v.key)} disabled={!data}>{v.label}</button>
          ))}
        </div>
        <button type="button" className={`pp-mm-toggle${showBase ? " is-on" : ""}`} aria-pressed={showBase} disabled={!data}
          onClick={() => { const v = !showBase; setShowBase(v); act((w) => w.setShowBase(v)); }}>100만 명 점 {showBase ? "켜짐" : "꺼짐"}</button>
        {view === "region" && (
          <button type="button" className={`pp-mm-toggle${hideNeutral ? " is-on" : ""}`} aria-pressed={hideNeutral}
            onClick={() => chooseNeutral(!hideNeutral)}>중립 빼고 보기</button>
        )}
      </div>

      <div className="pp-mm-body">
        <div className="pp-mm-stage">
          <div className="pp-mm-map" ref={wrap}>
            <canvas ref={baseCv} className="pp-mm-cv" aria-hidden="true" />
            <canvas ref={topCv} className="pp-mm-cv is-top" role="img"
              aria-label={`한국 지도 위 합성 인물 100만 명의 점과, 그중 1만 명이 ${m ? `${m.short} 대책에` : ""} 답한 색`} />
            {labels.map((l, i) => (
              <div key={i} className={`pp-mm-label is-${l.align ?? "left"}${l.tone ? ` is-${l.tone}` : ""}`} style={{ left: l.x, top: l.y }}>
                <b>{l.text}</b>{l.sub && <span>{l.sub}</span>}{l.value && <em>{l.value}</em>}
              </div>
            ))}
            {view === "map" && data && (
              <div className="pp-mm-count" aria-live="off"><span ref={counter}>0</span>명 <small>화면 속 인물</small></div>
            )}
            {view === "map" && data && (
              <div className="pp-mm-zoom">
                <button type="button" onClick={() => zoom(1.8)} aria-label="확대">＋</button>
                <button type="button" onClick={() => zoom(1 / 1.8)} aria-label="축소">−</button>
                <button type="button" onClick={() => act((w) => w.flyTo(w.fitCamera(), 1100))}>전국</button>
                <button type="button" onClick={() => act((w) => w.flyTo({ ...SEOUL, z: Math.min(SEOUL.z, (w.cssW - 24) / 42) }, 1200))}>서울</button>
              </div>
            )}
            {hint && view === "map" && <div className="pp-mm-hint">두 손가락으로 확대·이동합니다</div>}
            {!data && (
              <div className="pp-mm-loading">
                {error ? <p>지도를 불러오지 못했습니다. ({error})</p> : (
                  <>
                    <p>점 100만 개를 불러오는 중 · {pct(progress)}</p>
                    <div className="pp-mm-progress"><i style={{ width: pct(progress) }} /></div>
                  </>
                )}
              </div>
            )}
          </div>
          <ul className="pp-mm-legend">
            <li><span style={{ background: "#256ef4" }} />찬성 쪽</li>
            <li><span style={{ background: "#b1b8be" }} />중립</li>
            <li><span style={{ background: "#d63d4a" }} />반대 쪽</li>
            <li><span className="is-ink" />1만 명에 뽑히지 않은 인물</li>
          </ul>
          <p className="pp-mm-note">점 하나가 인물 한 명입니다. 점의 위치는 시군구까지만 실제이고, 시군구 안에서는 읍면동 넓이에 맞춰 흩었습니다. 1만 명의 점 색은 각자의 확률에서 한 번 뽑은 답이라, 색 비율과 오른쪽 평균 확률이 1~2%p 다를 수 있습니다.</p>
        </div>

        <aside className="pp-mm-side" aria-live="polite">
          {m && (
            <div className="pp-mm-card">
              <div className="pp-mm-kicker">{m.date.replaceAll("-", ".")} · {m.agency}</div>
              <h3>{m.title}</h3>
              {national && <><div className="pp-mm-sub">전국 1만 명 · 평균 확률</div><ShareBar s={national} /></>}
            </div>
          )}
          <div className="pp-mm-card">
            <label className="pp-mm-sub" htmlFor="pp-mm-district">시군구로 가기</label>
            <select id="pp-mm-district" className="pp-mm-select" value={district} onChange={(e) => goDistrict(Number(e.target.value))} disabled={!data}>
              <option value={-1}>시군구 선택</option>
              {provinces.map((g) => (
                <optgroup key={g.p} label={g.p}>{g.items.map((it) => <option key={it.j} value={it.j}>{it.name}</option>)}</optgroup>
              ))}
            </select>
            {meta && district >= 0 && local && (
              <div className="pp-mm-district">
                <h4>{meta.districts[district].name}</h4>
                <p className="pp-mm-sub">100만 명 중 {meta.districts[district].n.toLocaleString()}명 · 1만 명 중 {local.n.toLocaleString()}명</p>
                {local.n >= 30 ? <ShareBar s={local} /> : <p className="pp-mm-sub">표본이 30명보다 적어 해석하지 않습니다.</p>}
                <button type="button" className="pp-mm-link" onClick={() => goDistrict(-1)}>선택 해제</button>
              </div>
            )}
            {district < 0 && <p className="pp-mm-sub" style={{ marginTop: 8 }}>지도의 빈 곳을 누르면 그 시군구를 봅니다.</p>}
          </div>
          <div className="pp-mm-card">
            {!picked && <p className="pp-mm-sub">색 점을 누르면 그 인물과, 대책 10건에 대한 그 사람의 답을 봅니다.</p>}
            {picked && meta && data && (
              <div className="pp-mm-person">
                <div className="pp-mm-kicker">1만 명 중 한 사람</div>
                {picked.p ? (
                  <>
                    <h4>{picked.p.district} · {picked.p.age}세 · {picked.p.sex}</h4>
                    <p className="pp-mm-sub">{picked.p.occupation} · {picked.p.family} · {picked.p.housing}</p>
                    <p className="pp-mm-sub">배정한 점유 형태: {tenureText(picked.k)}</p>
                    <p className="pp-mm-sub is-fine">점유 형태는 공식 통계로 정한 가정이라 인물 소개와 다를 수 있습니다. 대책을 물을 때 이 가정을 함께 줬습니다.</p>
                    <p className="pp-mm-quote">{stripPersonaName(picked.p.text)}</p>
                  </>
                ) : <p className="pp-mm-sub">불러오는 중…</p>}
                <div className="pp-mm-mine">
                  {mine?.map((r, j) => (
                    <div key={r.short} className={`pp-mm-mine-row${j === measure ? " is-on" : ""}`}>
                      <span>{r.short}</span><ShareBar s={r.s} small /><em>{pct(r.s.favor)}</em>
                    </div>
                  ))}
                </div>
                <button type="button" className="pp-mm-link" onClick={() => { setPicked(null); act((w) => w.select(-1)); }}>닫기</button>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
