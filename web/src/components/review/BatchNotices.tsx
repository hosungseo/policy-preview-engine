"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { inputGuide } from "@/lib/modelGuide";
import { api, ApiError, type Notice, type NoticeText, type ServiceConfig } from "@/lib/reviewApi";
import ServiceGate from "./ServiceGate";

type Listing = { items: Notice[]; total: number | null; page?: number; more?: boolean; source: "api" | "web" };
type CartItem = { notice: Notice; question: string; options?: string[] };
type Review = { paraphrase: string; issues: { kind: string; message: string }[]; verdict: string; better: string };
type Pilot = { n: number; percent?: number[]; shift_pp?: number; undecided_pp?: number; flags: string[]; notes?: string[] };
type Candidate = { focus: string; question: string; options: string[]; basis: string; review: Review | null;
  pilot: Pilot | null; lint: { level: string; message: string }[]; revised_from?: string; recommended?: boolean };
type Step = { title: string; state: "waiting" | "working" | "queued" | "failed"; message?: string };
const OPTIONS = ["찬성", "반대", "잘 모르겠다"];
const DEFAULT_QUESTION = "이 개정안에 찬성하십니까?";
const CART_KEY = "pp-ask-cart-v1";

function cleanTitle(title: string): string {
  return title.replace(/^\[[^\]]*\]\s*/, "").replace(/\s*(재)?입법예고$/, "").slice(0, 100);
}

async function fetchText(notice: Notice): Promise<NoticeText> {
  const params = new URLSearchParams();
  if (notice.mapping_lbic_id && notice.announce_type) {
    params.set("mapping_lbic_id", notice.mapping_lbic_id);
    params.set("announce_type", notice.announce_type);
  }
  const suffix = params.size ? `?${params.toString()}` : "";
  return api<NoticeText>(`/api/lawmaking/${notice.seq}${suffix}`);
}

function loadCart(): CartItem[] {
  try {
    const raw = localStorage.getItem(CART_KEY);
    return raw ? (JSON.parse(raw) as CartItem[]) : [];
  } catch {
    return [];  // storage blocked or cleared: start with an empty cart
  }
}

function saveCart(cart: CartItem[]) {
  try {
    localStorage.setItem(CART_KEY, JSON.stringify(cart));
  } catch { /* the cart still works for this visit */ }
}

/** Question design (Elephant-Goldfish): drafted candidates, each reviewed by an isolated reader, for one notice. */
function Design({ notice, onUse }: { notice: Notice; onUse: (q: string, options: string[]) => void }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [cands, setCands] = useState<Candidate[]>([]);
  const [error, setError] = useState("");
  const [pilotN, setPilotN] = useState(0);
  async function run() {
    setState("busy");
    try {
      const found = await fetchText(notice);
      const out = await api<{ candidates: Candidate[]; pilot_n: number }>("/api/question-design", { method: "POST",
        body: { title: cleanTitle(found.title || notice.title), policy_text: found.text } });
      setCands(out.candidates);
      setPilotN(out.pilot_n);
      setState("done");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "문항 후보를 만들지 못했습니다.");
      setState("error");
    }
  }
  if (state === "idle") return <button type="button" className="rv-link" onClick={run}>문항 설계 도움</button>;
  if (state === "busy") return <p className="rv-muted">문항 후보를 만들고, 맥락 없는 검토자가 하나씩 읽고, 가상 인물에게 미리 물어보는 중… (모델에 따라 수 분~20분)</p>;
  if (state === "error") return <p className="rv-error">{error} <button type="button" className="rv-link" onClick={run}>다시</button></p>;
  return (
    <>
    <p className="rv-muted">검토자 판정 → 사전 시험 경고 수 순으로 정렬했습니다.{pilotN > 0 && ` 사전 시험은 AI 가상 인물 ${pilotN}명에게 선택지 순서를 바꿔 두 번 물은 결과입니다.`} 고르는 것은 사람의 몫입니다.</p>
    <ul className="rv-design">
      {cands.map((c) => {
        const r = c.review;
        const warns = c.lint.filter((f) => f.level !== "info");
        return (
          <li key={c.question} className={`is-${r ? (r.verdict === "좋음" ? "good" : r.verdict === "고쳐 쓰기" ? "fix" : "bad") : "none"}`}>
            <p className="rv-design-q">{c.recommended && <span className="pp-chip rv-design-best">추천</span>} <span className="pp-chip">{c.focus}</span> {c.question}</p>
            {c.revised_from && <p className="rv-muted">원래 문항: {c.revised_from} → 검토자 수정안을 다른 검토자가 다시 읽었습니다.</p>}
            <p className="rv-muted">선택지: {c.options.join(" · ")}</p>
            {c.basis && <p className="rv-muted">근거 문안: “{c.basis}”</p>}
            {r ? (
              <div className="rv-design-review">
                <p><b>검토자 판정: {r.verdict}</b> <span className="rv-muted">(이 문항만 보고 읽은 독립 검토)</span></p>
                <p>읽는 사람은 이렇게 이해합니다: {r.paraphrase}</p>
                {r.issues.map((i) => <p key={i.message} className="rv-design-issue">{i.kind}: {i.message}</p>)}
                {r.better && <p>고친 문항 제안: {r.better}</p>}
              </div>
            ) : <p className="rv-design-issue">독립 검토가 실행되지 않았습니다. 문제 없음이 아닙니다.</p>}
            {c.pilot && (c.pilot.n > 0 ? (
              <div className="rv-design-pilot">
                <p>사전 시험({c.pilot.n}명 · 실제 사람 응답 0명) · 순서 바꿈 차이 <b>{c.pilot.shift_pp}%p</b></p>
                {c.pilot.flags.length === 0
                  ? <p className="rv-muted">경고 없음: 선택지 순서에 덜 흔들리고 ‘모름’이 많지 않았습니다.</p>
                  : c.pilot.flags.map((f) => <p key={f} className="rv-design-issue">사전 시험: {f}</p>)}
                {c.pilot.notes?.map((f) => <p key={f} className="rv-muted">참고: {f}</p>)}
                <details className="rv-more">
                  <summary>참고용 내부 지표 (사전 시험 선택지 분포)</summary>
                  <p className="rv-muted">{c.options.map((o, i) => `${o} ${c.pilot!.percent?.[i] ?? 0}%`).join(" · ")}</p>
                </details>
              </div>
            ) : <p className="rv-design-issue">사전 시험이 실행되지 않았습니다. 문제 없음이 아닙니다.</p>)}
            {warns.map((f) => <p key={f.message} className="rv-design-issue">규칙 점검: {f.message}</p>)}
            <button type="button" className="krds-btn small secondary" onClick={() => onUse(c.question, c.options)}>이 문항 쓰기</button>
          </li>
        );
      })}
    </ul>
    </>
  );
}

/** One notice in the browse list: open its text, put it in the cart. */
function Row({ n, inCart, full, onToggle }: { n: Notice; inCart: boolean; full: boolean; onToggle: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  async function show() {
    setOpen((o) => !o);
    if (text === null) {
      try {
        setText((await fetchText(n)).text);
      } catch (e) {
        setText(e instanceof ApiError ? e.message : "내용을 불러오지 못했습니다.");
      }
    }
  }
  return (
    <li className={inCart ? "is-on" : undefined}>
      <div className="rv-cart-row">
        <span><strong>{cleanTitle(n.title)}</strong>
          <span className="rv-muted">{[n.agency, n.kind, n.period].filter(Boolean).join(" · ")}</span></span>
        <span className="rv-cart-row-actions">
          <button type="button" className="rv-link" onClick={show}>{open ? "내용 접기" : "내용 보기"}</button>
          <button type="button" className={`krds-btn small ${inCart ? "primary" : "secondary"}`} onClick={onToggle}
            disabled={!inCart && full}>{inCart ? "담김 ✓" : "담기"}</button>
        </span>
      </div>
      {open && <p className="rv-cart-text">{text ?? "불러오는 중…"}</p>}
    </li>
  );
}

/** A cart of open legislative notices: browse and scroll, put in what to ask, set a question for each, run in turn. */
function Cart({ config }: { config: ServiceConfig }) {
  const [query, setQuery] = useState("");
  const [shownQuery, setShownQuery] = useState("");
  const [items, setItems] = useState<Notice[]>([]);
  const [page, setPage] = useState(0);
  const [more, setMore] = useState(true);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [cart, setCart] = useState<CartItem[]>([]);
  const [steps, setSteps] = useState<Step[] | null>(null);
  const sentinel = useRef<HTMLLIElement | null>(null);
  const limit = config.daily_runs;

  useEffect(() => { setCart(loadCart()); }, []);
  const update = (next: CartItem[]) => { setCart(next); saveCart(next); };

  const load = useCallback(async (q: string, nextPage: number) => {
    setLoading(true);
    setError("");
    try {
      const res = await api<Listing>(`/api/lawmaking?q=${encodeURIComponent(q)}&page=${nextPage}`);
      setItems((prev) => {
        const seen = new Set(prev.map((n) => n.seq));
        return nextPage === 1 ? res.items : [...prev, ...res.items.filter((n) => !seen.has(n.seq))];
      });
      setPage(nextPage);
      setMore(!!res.more);
      setTotal(res.total);
      setShownQuery(q);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "입법예고를 불러오지 못했습니다. 다시 시도해 주세요.");
      setMore(false);
    }
    setLoading(false);
  }, []);
  useEffect(() => { load("", 1); }, [load]);

  // Scrolling to the end of the list loads the next page.
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !more) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && !loading) load(shownQuery, page + 1);
    }, { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [more, loading, page, shownQuery, load]);

  function toggle(n: Notice) {
    if (cart.some((c) => c.notice.seq === n.seq)) update(cart.filter((c) => c.notice.seq !== n.seq));
    else if (cart.length < limit) update([...cart, { notice: n, question: DEFAULT_QUESTION }]);
  }

  async function start() {
    const queue = cart.filter((c) => c.question.trim().length >= 5);
    if (!queue.length) return;
    setSteps(queue.map((c) => ({ title: cleanTitle(c.notice.title), state: "waiting" })));
    for (let i = 0; i < queue.length; i++) {
      const set = (patch: Partial<Step>) => setSteps((s) => s && s.map((x, j) => (j === i ? { ...x, ...patch } : x)));
      set({ state: "working" });
      try {
        const found = await fetchText(queue[i].notice);
        const { id } = await api<{ id: string }>("/api/surveys", { method: "POST",
          body: { title: cleanTitle(found.title || queue[i].notice.title), policy_text: found.text } });
        await api(`/api/surveys/${id}/runs`, { method: "POST", body: { question: queue[i].question.trim(), options: queue[i].options ?? OPTIONS } });
        set({ state: "queued" });
      } catch (e) {
        set({ state: "failed", message: e instanceof ApiError ? e.message : "접수하지 못했습니다." });
      }
    }
    update([]);
  }

  if (steps) {
    const done = steps.every((s) => s.state === "queued" || s.state === "failed");
    return (
      <div className="pp-card rv-batch">
        <h2 className="pp-h3">{steps.length}건을 맡겼습니다</h2>
        <p className="rv-muted">한 건씩 차례로 묻습니다. 창을 닫아도 계속되니, 나중에 목록에서 건별 결과를 보세요.</p>
        <ol className="rv-batch-steps">
          {steps.map((s) => (
            <li key={s.title} className={`is-${s.state}`}>
              <span>{s.title}</span>
              <span className="rv-muted">{s.state === "waiting" ? "대기" : s.state === "working" ? "가져와 맡기는 중…" : s.state === "queued" ? "맡김" : `실패 — ${s.message}`}</span>
            </li>
          ))}
        </ol>
        {done && <Link href="/review/" className="krds-btn medium primary">목록으로</Link>}
      </div>
    );
  }

  const inCart = new Set(cart.map((c) => c.notice.seq));
  return (
    <>
      <div className="pp-card rv-form rv-batch">
        <div className="rv-notice-search">
          <input className="krds-input" aria-label="입법예고 이름 검색" value={query} maxLength={50}
            placeholder="법령 이름 일부 (비우면 의견 접수 중인 입법예고 전체)" onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); load(query.trim(), 1); } }} />
          <button type="button" className="krds-btn medium secondary" disabled={loading} onClick={() => load(query.trim(), 1)}>입법예고 검색</button>
        </div>
        {error && <p className="rv-error" role="alert">{error}</p>}
        <p className="rv-muted">
          {shownQuery ? `‘${shownQuery}’ 검색 결과` : "의견 접수 중인 입법예고(최근순)"}
          {total != null && ` 전체 ${total.toLocaleString()}건`} · 내려가면 더 불러옵니다 · 하루 {limit}건까지 담을 수 있습니다
        </p>
        <ul className="rv-batch-list">
          {items.map((n) => (
            <Row key={n.seq} n={n} inCart={inCart.has(n.seq)} full={cart.length >= limit} onToggle={() => toggle(n)} />
          ))}
          {more && <li ref={sentinel} className="rv-muted rv-cart-more">{loading ? "불러오는 중…" : "더 불러오기"}</li>}
          {!more && items.length > 0 && <li className="rv-muted rv-cart-more">목록 끝입니다.</li>}
        </ul>
      </div>
      <aside className={`rv-cart${cart.length ? " is-filled" : ""}`} aria-label="물어볼 목록">
        <details>
          <summary><b>물어볼 목록 {cart.length}건</b> <span className="rv-muted">{cart.length ? "· 눌러서 건마다 문항을 정하고 맡기세요" : "· 위에서 ‘담기’ 하세요"}</span></summary>
          {cart.length === 0 && <p className="rv-muted">위 목록에서 국민에게 묻고 싶은 입법예고를 ‘담기’ 하세요.</p>}
          <ol className="rv-cart-items">
            {cart.map((c, i) => (
              <li key={c.notice.seq}>
                <div className="rv-cart-item-head">
                  <strong>{cleanTitle(c.notice.title)}</strong>
                  <button type="button" className="rv-link" onClick={() => update(cart.filter((x) => x.notice.seq !== c.notice.seq))}>빼기</button>
                </div>
                <input className="krds-input" aria-label={`${i + 1}번째 입법예고에 물을 문항`} maxLength={config.max_question}
                  value={c.question} onChange={(e) => update(cart.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)))} />
                <p className="rv-muted">선택지: {(c.options ?? OPTIONS).join(" · ")}</p>
                <Design notice={c.notice} onUse={(q, options) => update(cart.map((x, j) => (j === i ? { ...x, question: q, options } : x)))} />
              </li>
            ))}
          </ol>
          {cart.length > 0 && (
            <div className="rv-cart-foot">
              <p className="form-hint">{inputGuide(config.model_profile)}</p>
              <button type="button" className="krds-btn large primary" onClick={start}
                disabled={cart.every((c) => c.question.trim().length < 5)}>{cart.length}건 물어보기 시작</button>
              <p className="rv-muted">건마다 합성 국민 {config.n.toLocaleString()}명에게 묻습니다. 한 건에 10분 안팎이고, 차례로 진행됩니다.</p>
            </div>
          )}
        </details>
      </aside>
    </>
  );
}

export default function BatchNotices() {
  return <ServiceGate>{(_, config) => <Cart config={config} />}</ServiceGate>;
}
