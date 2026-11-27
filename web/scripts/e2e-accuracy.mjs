// Offline browser regression: intercept every request; no server or network needed.
// PP_WEB_OUT=/path/to/isolated/out PLAYWRIGHT_BROWSERS_PATH=../data/ms-playwright node scripts/e2e-accuracy.mjs
import assert from 'node:assert/strict';
import { readFile, stat, mkdir } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';

export async function accuracyFixtures(browser) {
  const root = resolve(process.env.PP_WEB_OUT ?? 'out');
  const out = resolve(process.env.PP_OUT ?? '/private/tmp/egm-accuracy-e2e');
  await mkdir(out, { recursive: true });
  let checks = 0;
  for (const name of ['applied', 'not_applied', 'unverified', 'legacy', 'verified', 'mismatch', 'zero', 'partial', 'null_mean', 'historical', 'historical_mismatch']) {
    const isHistorical = name.startsWith('historical');
    const state = isHistorical ? 'not_applied' : ['verified', 'mismatch', 'zero', 'partial', 'null_mean'].includes(name) ? 'applied' : name;
    const baseline = ['verified', 'mismatch', 'zero', 'partial', 'null_mean'].includes(name) ? {
      status: 'verified', mae_pp: name === 'zero' ? 0 : name === 'null_mean' ? null : 2.5,
      worst_pp: name === 'partial' ? null : 7, inputs: { model: { model_revision: name === 'mismatch' ? 'other' : 'fixture-model' } },
      question_ids: ['q1', 'q2', 'q3'], scope: { min_age: 20 }, excluded_reasons: ['sex_adult_cross_table_missing'],
    } : null;
    const accuracy = { schema_version: 2, kind: 'api_accuracy', payload: {
      state, model_revision: state === 'applied' ? 'fixture-model' : null,
      manifest_hash: state === 'applied' ? 'fixture-manifest' : null, applied_rate: state === 'applied' ? .96 : null,
      scope: { year: 2024, population: '20세 이상 개인', min_age: 20, max_age: null, unit: 'adult_person' },
      baseline, reasons: state === 'unverified' ? ['source_unverified'] : state === 'not_applied' ? ['baseline_unavailable', 'model_unverified', 'enrichment_not_applied', 'unknown_code', 'unknown_code_2'] : [],
    } };
    if (isHistorical) {
      accuracy.payload.reasons = ['model_unverified', ...(name === 'historical_mismatch' ? ['historical_model_mismatch'] : [])];
      accuracy.payload.historical_baseline = {
        status: 'verified', evaluation_kind: 'historical_diagnostic', mae_pp: 4.2, worst_pp: 19,
        reverse_mae_pp: 4.5, question_ids: ['a','b','c','d','e'], scope: accuracy.payload.scope,
        inputs: { model: { model_revision: 'jev-fixture' } }, panel_version: 'fixture', source: '2024 사회조사',
        model_identity_verified: false, unsure_signed_pp: [1,2], artifact_hash: 'a'.repeat(64),
        excluded_reasons: ['historical_development_only', 'model_identity_unproven', 'population_standard_caveat'],
      };
    }
    const result = { n: 100, options: ['찬성', '반대'], percent: [60, 40], top: 0, placebo_shift_pp: 1,
      reversal_shift_pp: 2, unstable: false, splits: [], axes: [], baseline: { mae_pp: 99 },
      next_action: { kind: 'real_survey', text: '실제 조사로 확인하세요.' }, lint_warnings: 0,
      summary_text: '구 기준선 ±99%p', cautions: [], ...(state === 'legacy' ? {} : { accuracy }) };
    const survey = { id: 'fixture', title: '시험', policy_text: '시험 정책', runs: [{ id: 'run', status: 'succeeded',
      spec: { question: '정책에 찬성하십니까?', options: result.options }, result, lint: [], created_at: '2024-01-01T00:00:00Z' }] };
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, permissions: ['clipboard-read', 'clipboard-write'] });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://localhost') return route.abort();
      const api = { '/api/config': { service: true, mock: true, baseline: { mae_pp: 99 } },
        '/api/me': { email: 'fixture@example.test' }, '/api/surveys/fixture': survey };
      if (url.pathname in api) return route.fulfill({ json: api[url.pathname] });
      let file = resolve(root, '.' + decodeURIComponent(url.pathname));
      if (!file.startsWith(root + '/')) return route.abort();
      try {
        if ((await stat(file)).isDirectory()) file += '/index.html';
        const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
          '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
        return route.fulfill({ body: await readFile(file), contentType: types[extname(file)] ?? 'application/octet-stream' });
      } catch { return route.fulfill({ status: 404, body: '' }); }
    });
    try {
      await page.goto('http://localhost/review/view/?id=fixture');
      await page.waitForSelector('.rv-result');
      const shown = await page.textContent('.rv-result');
      const expected = state === 'applied' ? '공공통계로 배정한 가정' : state === 'legacy' ? '과거 5개 진단 문항' :
        state === 'unverified' ? '보완 여부와 검증 상태를 확인할 수 없습니다' : '공공통계 속성 보완은 적용하지 않았습니다';
      assert.ok(shown.includes(expected)); checks++;
      assert.ok(!/±|99%p|미산출%p|baseline_unavailable|model_unverified|enrichment_not_applied|unknown_code/.test(shown)); checks++;
      assert.deepEqual(await page.locator('.rv-result').evaluate(el => Array.from(el.children).slice(0, 2).map(child => child.className)), ['rv-label', 'rv-question']); checks++;
      assert.equal(await page.locator('.rv-status').count(), 1); checks++;
      assert.equal(await page.locator('.rv-more[open]').count(), 0); checks++;
      if (baseline && name !== 'mismatch') {
        assert.ok(shown.includes('3개 문항 · 20세 이상'));
        assert.ok(shown.includes(baseline.mae_pp == null ? '미산출' : `${baseline.mae_pp}%p`));
        assert.ok(shown.includes(baseline.worst_pp == null ? '최악 선택지 차이 미산출' : '최악 선택지 차이 7%p'));
        checks += 3;
      } else if (isHistorical) {
        assert.ok(shown.includes('검증됨(과거 진단 5문항, 2024 사회조사)'));
        assert.ok(shown.includes('현재 모델판 동일성 미확인'));
        assert.ok(shown.includes('4.2%p'));
        assert.ok(shown.includes('이 문항의 오차 범위 아님')); checks += 4;
      } else { assert.ok(shown.includes('검증 전')); checks++; }
      if (name === 'mismatch') { assert.ok(shown.includes('모델판이 달라')); assert.ok(!shown.includes('2.5%p')); checks += 2; }
      if (name === 'unverified') { assert.ok(shown.includes('출처 검증이 완료되지')); assert.ok(!shown.includes('속성 보완 미적용')); checks += 2; }
      if (baseline) { assert.ok(shown.includes('성별·성인 교차 통계')); checks++; }
      await page.click("button:has-text('요약 문장 복사')");
      const copied = await page.evaluate(() => navigator.clipboard.readText());
      assert.ok(copied.includes('실제 여론조사 아님'));
      assert.ok(copied.includes(isHistorical || baseline?.mae_pp != null && name !== 'mismatch' ? '이 문항의 오차 범위는 아닙니다.' : '실측 비교 검증 전이며 실제 조사로 확인이 필요합니다.'));
      if (isHistorical) {
        assert.ok(copied.includes('과거 진단 5문항(2024 사회조사)'));
        assert.ok(copied.includes('4.2%p'));
        assert.ok(copied.includes('동일성은 미확인')); checks += 3;
      }
      assert.ok(!/±|99%p/.test(copied)); checks += 2;
      if (baseline && baseline.mae_pp != null && name !== 'mismatch') { assert.ok(copied.includes(`${baseline.mae_pp}%p`)); checks++; }
      if (baseline) { assert.ok(!copied.includes('성별·성인 교차 통계')); checks++; }
      if (name === 'unverified') { assert.ok(!copied.includes('출처 검증이 완료되지')); checks++; }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)); checks++;
      assert.deepEqual(errors, []); checks++;
      await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
      console.log(`PASS ${name}: 390px, display, clipboard, baseline scope`);
    } finally { await context.close(); }
  }
  console.log(`${checks}/${checks} accuracy checks passed`);
}
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const browser = await chromium.launch();
  try { await accuracyFixtures(browser); } finally { await browser.close(); }
}
