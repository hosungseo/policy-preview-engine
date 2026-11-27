import type { Persona } from "./types";

export const SUPPORT_LABEL: Record<string, string> = {
  "-2": "강한 반대", "-1": "반대", "0": "중립", "1": "찬성", "2": "강한 찬성",
};

export const PROVINCE_DISPLAY: Record<string, string> = {
  서울: "서울", 부산: "부산", 대구: "대구", 인천: "인천", 광주: "광주", 대전: "대전", 울산: "울산", 세종: "세종",
  경기: "경기", 강원: "강원", 충청북: "충북", 충청남: "충남", 전북: "전북", 전라남: "전남", 경상북: "경북",
  경상남: "경남", 제주: "제주",
};

export const KIND_CLASS: Record<string, string> = {
  입법예고: "krds-badge bg-primary",
  "가상 정책안": "krds-badge bg-gray",
  "정책 요약": "krds-badge bg-secondary",
};

export const STAGES: { key: string; title: string; desc: string }[] = [
  { key: "segment", title: "정책문 나누기", desc: "조항·항목 단위로 나눠 반응이 어디에 몰리는지 잴 수 있게 합니다." },
  { key: "clarity", title: "정책문 점검", desc: "조항마다 어려운 용어·대상 모호 등 8가지 문제와 안내문 체크리스트 6가지를 Jev가 봅니다." },
  { key: "panel", title: "패널 구성", desc: "100만 명에서 대표 패널을 층화 추출하고, 영향권 인물을 세 경로로 찾습니다." },
  { key: "react", title: "반응 수집", desc: "인물마다 따로 정책을 읽고 지지도·이유·반응한 문구를 답합니다." },
  { key: "issues", title: "쟁점 묶기·점검", desc: "LLM이 쟁점과 보완 제안을 묶고, Jev가 반응마다 쟁점 소속과 자기모순을 판정합니다." },
  { key: "jev", title: "정량 점검(Jev)", desc: "5,000명에게 찬반·영향·조항별 찬반·쟁점 공감·참여 방식을 한 번의 호출로 묻습니다." },
  { key: "alternatives", title: "수정안 비교", desc: "보완 제안으로 만든 수정안을 같은 1,500명에게 원안·대조 문장과 비교해 묻습니다." },
  { key: "review", title: "판정 점검", desc: "선택지 순서·질문 묶음·반복 호출·직업 분류를 점검하고, 반응마다 관점 12가지를 붙입니다." },
  { key: "analyze", title: "분석", desc: "집단별 차이, 쟁점 확산도, 찾아가 들어야 할 집단과 권장 방식을 계산합니다." },
  { key: "hearing", title: "가상 공청회", desc: "입장이 갈리는 6명이 세 라운드에 걸쳐 토론합니다." },
  { key: "debrief", title: "발언 읽기", desc: "Jev가 공청회 발언을 하나씩 읽어 태도 변화와 반박·입장 완화·제안을 표시합니다." },
  { key: "plan", title: "계획서", desc: "의견수렴 계획서 초안을 만듭니다." },
];

export const CHANNEL_LABEL: Record<string, string> = { filter: "속성 조건", fts: "키워드", semantic: "의미 검색" };

// A non-zero share never shows as 0%, and a partial share never shows as 100%.
export function pct(x: number | null, digits = 0): string {
  if (x === null) return "불명";
  const text = (x * 100).toFixed(digits);
  const zero = Number(text) === 0;
  if ((x > 0 && zero) || (x < 1 && Number(text) === 100)) {
    const fine = (x * 100).toFixed(digits + 1);
    if (x > 0 && Number(fine) === 0) return `<${(10 ** -(digits + 1)).toFixed(digits + 1)}%`;
    if (x < 1 && Number(fine) === 100) return `>${(100 - 10 ** -(digits + 1)).toFixed(digits + 1)}%`;
    return `${fine}%`;
  }
  return `${text}%`;
}

export function signed(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  const v = Math.abs(x) < 0.5 * 10 ** -digits ? 0 : x;
  return v > 0 ? `+${v.toFixed(digits)}` : v.toFixed(digits);
}

// A probability difference as signed percentage points, e.g. -0.034 -> "−3.4".
export function ppoint(x: number, digits = 1): string {
  const v = Math.abs(x * 100) < 0.5 * 10 ** -digits ? 0 : x * 100;
  return v > 0 ? `+${v.toFixed(digits)}` : v < 0 ? `−${Math.abs(v).toFixed(digits)}` : (0).toFixed(digits);
}

// 10000 -> "1만 명", 2500 -> "2,500명".
export function peopleKo(n: number): string {
  return n >= 10000 && n % 10000 === 0 ? `${n / 10000}만 명` : `${n.toLocaleString()}명`;
}

export function duration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}초`;
  if (s >= 3600) {
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return m ? `${h}시간 ${m}분` : `${h}시간`;
  }
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}분 ${r}초` : `${m}분`;
}

// Runs are stamped in UTC; pages show the Korean calendar date whatever the build machine's zone.
const KST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "numeric", day: "numeric" });

export function dateKo(iso: string): string {
  const parts = Object.fromEntries(KST_DATE.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  return `${parts.year}. ${Number(parts.month)}. ${Number(parts.day)}.`;
}

export function personaTitle(p: Persona): string {
  return `${p.sex === "여자" ? "여성" : "남성"} · ${p.age}세 · ${p.occupation}`;
}

export function personaPlace(p: Persona): string {
  const district = p.district.includes("-") ? p.district.split("-").slice(1).join("-") : p.district;
  return `${p.province} ${district}`.trim();
}

export function personaShort(p: Persona): string {
  return `합성 인물(${p.age}세·${p.occupation})`;
}

export function personaAnonBadge(p: Pick<Persona, "age">): string {
  const band = Math.floor(p.age / 10) * 10;
  return band >= 70 ? "70+" : `${band}대`;
}

/** Mask leading synthetic Korean real names (e.g. "박준환 씨는 ...") in static persona snippets for display. */
export function stripPersonaName(text: string): string {
  const map: Record<string, string> = { 는: "은", 가: "이", 를: "을", 와: "과" };
  return text.replace(
    /^\s*[가-힣]{2,4}\s*씨(는|가|의|도|에게|와|과|를|을)?/,
    (_, particle = "") => `이 합성 인물${map[particle] ?? particle}`,
  );
}
