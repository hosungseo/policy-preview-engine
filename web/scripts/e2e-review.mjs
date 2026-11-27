// Browser E2E for 합성 여론 미리보기 against running ppservice instances.
//   PP_BASE=http://127.0.0.1:8810 (PP_JEV_PROVIDER=mock)  PP_CODE_A=… PP_CODE_B=…
//   PP_FAIL_BASE=http://127.0.0.1:8811 (PP_JEV_PROVIDER=fail) PP_FAIL_CODE=…
//   PP_OUT=e2e-out PLAYWRIGHT_BROWSERS_PATH=../data/ms-playwright node scripts/e2e-review.mjs
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";
import { accuracyFixtures } from "./e2e-accuracy.mjs";

const BASE = process.env.PP_BASE ?? "http://127.0.0.1:8810";
const OUT = process.env.PP_OUT ?? "e2e-out";
const POLICY = "○○시는 2027년 1월 1일부터 만 70세 이상 시민에게 시내버스 요금을 전액 지원합니다. 1인당 월 지원 한도는 5만 원이며, 시외버스와 관광용 전세버스는 제외합니다.";
mkdirSync(OUT, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + String(detail).slice(0, 140) : ""}`);
};

async function login(page, base, email, code) {
  await page.goto(`${base}/review/`);
  await page.waitForURL(/\/review\/login\//);
  await page.fill("#rv-email", email);
  await page.fill("#rv-code", code);
  await page.click("button[type=submit]");
  await page.waitForURL((u) => !u.pathname.includes("/login/"));
}

async function fillNew(page, question) {
  await page.fill("#rv-title", "고령층 시내버스 요금 지원(시험)");
  await page.fill("#rv-policy", POLICY);
  await page.fill("#rv-question", question);
}

const browser = await chromium.launch();
try {
  const ctxA = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctxA.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/status of 401/.test(m.text())) consoleErrors.push(m.text()); });

  await login(page, BASE, "a@test.go.kr", process.env.PP_CODE_A);
  await page.waitForSelector(".rv-empty, .rv-list");
  check("로그인 후 빈 목록", await page.isVisible("text=아직 미리보기가 없습니다"));

  await page.goto(`${BASE}/review/new/`);
  await page.waitForSelector("#rv-title");
  await page.click("button:has-text('미리 돌려보기')");
  check("필수 입력 누락 안내", /정책 이름/.test(await page.textContent(".rv-error")));

  await fillNew(page, "세금 낭비인 시내버스 요금 지원에 찬성하십니까?");
  await page.waitForSelector(".rv-lint .is-warn");
  check("입력 중 문항 점검(유도 표현)", /세금 낭비/.test(await page.textContent(".rv-lint")));
  await page.fill("#rv-question", "다음 지방선거에서 시장 후보를 지지하십니까?");
  await page.waitForSelector(".rv-lint .is-block");
  check("선거 문항 실행 불가 표시", /선거/.test(await page.textContent(".rv-lint")));
  await page.screenshot({ path: `${OUT}/01-lint.png`, fullPage: true });
  await page.fill("#rv-question", "만 70세 이상 시내버스 요금 전액 지원에 찬성하십니까?");
  await page.waitForSelector(".rv-lint-ok");
  await page.click("button:has-text('미리 돌려보기')");
  await page.waitForURL(/\/review\/view\/\?id=/);
  const url = page.url();
  await page.waitForSelector(".rv-job.is-running, .rv-result");
  check("진행 상태 또는 결과 표시", true, await page.textContent(".rv-job.is-running, .rv-result"));
  await page.screenshot({ path: `${OUT}/02-running.png` });

  await page.close();
  const p2 = await ctxA.newPage();
  await p2.goto(url);
  await p2.waitForSelector(".rv-result", { timeout: 120000 });
  const text = await p2.textContent(".rv-result");
  check("창을 닫았다 다시 열어도 결과 복원", true);
  check("결과: % 표시 + '실제 여론조사 아님' + 신뢰 지표", /실제 여론조사 아님/.test(text) && /\d+%/.test(text) && /대조 문장 효과/.test(text) && /순서 흔들림/.test(text));
  check("화면에 '국민'·'표본오차' 없음", !/국민\s?\d|표본오차 ±|신뢰수준 95/.test(text));
  check("실측 비교 상태와 한계 표시", /비교 문항 평균 절대 차이/.test(text) && /(검증 전|검증됨)/.test(text) && /이 문항의 오차 범위(가 아닙니다| 아님)/.test(text) && !text.includes("±"), text.match(/실측 비교[^·]*·[^·]*/)?.[0]);
  check("다음 할 일 한 줄", (await p2.locator(".rv-next").count()) === 1, await p2.textContent(".rv-next"));
  await p2.screenshot({ path: `${OUT}/03-result.png`, fullPage: true });

  await p2.click("button:has-text('문항 고쳐 다시 돌리기')");
  await p2.fill("#rv-question", "만 70세 이상 시내버스 요금을 전액 지원하는 것에 대해 어떻게 생각하십니까?");
  await p2.waitForTimeout(600);
  await p2.click("button:has-text('다시 돌리기')");
  await p2.waitForSelector(".rv-earlier", { timeout: 120000 });
  await p2.waitForSelector(".rv-result", { timeout: 120000 });
  check("다시 돌리면 이전 문항이 나란히 남음", /이전에 돌린 문항/.test(await p2.textContent(".rv-earlier")));

  const id = new URL(url).searchParams.get("id");
  const ids = await p2.evaluate(async (sid) => {
    const body = JSON.stringify({ question: "만 70세 이상 시내버스 요금 지원에 찬성하십니까?", options: ["찬성", "반대", "잘 모르겠다"] });
    const post = () => fetch(`/api/surveys/${sid}/runs`, { method: "POST", headers: { "X-PP-Client": "web", "Content-Type": "application/json" }, body }).then((r) => r.json());
    const all = await Promise.all([post(), post(), post()]);
    return [...new Set(all.map((x) => x.run && x.run.id))].length + ":" + all.map((x) => x.created).filter(Boolean).length;
  }, id);
  check("동시 중복 요청 3건 → 실행 1건", ids === "1:1", ids);
  await p2.reload();
  await p2.waitForSelector(".rv-result", { timeout: 120000 });

  const ctxB = await browser.newContext();
  const pb = await ctxB.newPage();
  await login(pb, BASE, "b@test.go.kr", process.env.PP_CODE_B);
  await pb.waitForSelector(".rv-empty, .rv-list");
  check("다른 사용자 목록에 안 보임", await pb.isVisible("text=아직 미리보기가 없습니다"));
  await pb.goto(url);
  await pb.waitForSelector(".rv-error");
  check("다른 사용자가 주소로 열면 차단", /찾을 수 없습니다/.test(await pb.textContent(".rv-error")));

  const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, storageState: await ctxA.storageState() });
  const pm = await mob.newPage();
  await pm.goto(url);
  await pm.waitForSelector(".rv-result");
  const overflow = await pm.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check("휴대폰 너비 가로 넘침 없음", overflow <= 1, `overflow=${overflow}`);
  await pm.screenshot({ path: `${OUT}/04-mobile.png`, fullPage: true });

  await accuracyFixtures(browser);

  // Display-only fixtures never register an active production manifest.
  const fixtureSurvey = await p2.evaluate(async (sid) => (await fetch(`/api/surveys/${sid}`)).json(), id);
  const fixtureConfig = await p2.evaluate(async () => (await fetch("/api/config")).json());
  for (const state of ["applied", "not_applied", "unverified", "legacy"]) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, storageState: await ctxA.storageState(),
      permissions: ["clipboard-read", "clipboard-write"] });
    const fp = await ctx.newPage();
    const survey = structuredClone(fixtureSurvey);
    survey.runs = [survey.runs.find((r) => r.status === "succeeded")];
    const result = survey.runs[0].result;
    result.baseline = { mae_pp: 6.5 };
    result.summary_text = "과거 오차 ±6.5%p";
    result.cautions = [];
    if (state === "legacy") delete result.accuracy;
    else result.accuracy = { schema_version: 2, kind: "api_accuracy", payload: {
      state, manifest_hash: null, model_revision: null, applied_rate: state === "applied" ? .96 : null,
      scope: null, baseline: null, reasons: ["fixture_unverified"] } };
    await fp.route("**/api/config", (route) => route.fulfill({ json: { ...fixtureConfig, baseline: { mae_pp: 99 } } }));
    await fp.route(`**/api/surveys/${id}`, (route) => route.fulfill({ json: survey }));
    await fp.goto(url);
    await fp.waitForSelector(".rv-result");
    const shown = await fp.textContent(".rv-result");
    const expected = state === "applied" ? "공공통계로 배정한 가정" : state === "legacy" ? "과거 5개 진단 문항, 비교 정의 제한 있음" : state === "unverified" ? "공공통계 속성 보완 여부와 검증 상태를 확인할 수 없습니다" : "공공통계 속성 보완은 적용하지 않았습니다";
    check(`${state}: 상태·검증 전·구 기준선 격리`, shown.includes(expected) && shown.includes("검증 전") && !/±|99%p|6.5%p/.test(shown));
    await fp.click("button:has-text('요약 문장 복사')");
    const copied = await fp.evaluate(() => navigator.clipboard.readText());
    check(`${state}: 복사문 한계`, copied.includes("실제 여론조사 아님") && copied.includes("실측 비교 검증 전이며 실제 조사로 확인이 필요합니다.") && !/baseline_unavailable|model_unverified|enrichment_not_applied|fixture_unverified/.test(copied) && !copied.includes("±"));
    check(`${state}: 390px 넘침 없음`, await fp.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await fp.screenshot({ path: `${OUT}/accuracy-${state}.png`, fullPage: true });
    await ctx.close();
  }

  if (process.env.PP_FAIL_BASE) {
    const pf = await (await browser.newContext()).newPage();
    await login(pf, process.env.PP_FAIL_BASE, "a@test.go.kr", process.env.PP_FAIL_CODE);
    await pf.goto(`${process.env.PP_FAIL_BASE}/review/new/`);
    await pf.waitForSelector("#rv-title");
    await fillNew(pf, "만 70세 이상 시내버스 요금 전액 지원에 찬성하십니까?");
    await pf.waitForSelector(".rv-lint-ok");
    await pf.click("button:has-text('미리 돌려보기')");
    await pf.waitForSelector(".rv-job.is-failed", { timeout: 180000 });
    const msg = await pf.textContent(".rv-job.is-failed");
    check("응답 모델 장애 → 이해 가능한 실패 안내", /연결하지 못했습니다/.test(msg) && !/Traceback|model_unavailable|JevError/.test(msg), msg);
    await pf.screenshot({ path: `${OUT}/05-failed.png` });
    await pf.click("button:has-text('다시 시도')");
    await pf.waitForSelector(".rv-job.is-running, .rv-job.is-failed");
    check("다시 시도 → 새 실행 접수", true);
  }
  check("브라우저 콘솔 오류 없음", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
