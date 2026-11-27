// Actual ResultView server rendering; does not replace browser E2E.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import swc from 'next/dist/build/swc/index.js';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
function load(file, overrides = {}) {
  const { code } = swc.transformSync(readFileSync(file, 'utf8'), {
    filename: file, module: { type: 'commonjs' },
    jsc: { parser: { syntax: 'typescript', tsx: file.endsWith('.tsx') },
      target: 'es2022', transform: { react: { runtime: 'automatic' } } },
  });
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, require: name => overrides[name] ?? require(name) });
  return module.exports;
}
const api = load('src/lib/reviewApi.ts');
const View = load('src/components/review/ResultView.tsx', { '@/lib/reviewApi': api,
  './QuestionEditor': { Findings: () => null }, './VisitView': () => null }).default;
for (const name of ['applied', 'not_applied', 'unverified', 'legacy', 'verified', 'mismatch', 'zero', 'partial', 'null_mean']) {
  const hasBaseline = ['verified', 'mismatch', 'zero', 'partial', 'null_mean'].includes(name);
  const state = hasBaseline ? 'applied' : name;
  const baseline = hasBaseline ? {
    status: 'verified', mae_pp: name === 'zero' ? 0 : name === 'null_mean' ? null : 2.5,
    worst_pp: name === 'partial' ? null : 7, question_ids: ['1', '2', '3'], scope: { min_age: 20 },
    inputs: { model: { model_revision: name === 'mismatch' ? 'other' : 'fixture' } },
    excluded_reasons: ['sex_adult_cross_table_missing'],
  } : null;
  const result = { n: 100, options: ['찬성', '반대'], percent: [60, 40], top: 0, axes: [], splits: [],
    next_action: { kind: 'real_survey', text: '실제 조사' }, baseline: { mae_pp: 99 },
    ...(state === 'legacy' ? {} : { accuracy: { payload: { state, baseline, model_revision: 'fixture',
      manifest_hash: 'fixture', reasons: ['source_unverified', 'baseline_unavailable', 'model_unverified', 'enrichment_not_applied', 'unknown_code', 'another_unknown_code'] } } }) };
  const html = renderToStaticMarkup(React.createElement(View, { run: { result, spec: { question: '시험' }, lint: [] }, config: {} }));
  assert.ok(!/±|99%p|미산출%p|baseline_unavailable|model_unverified|enrichment_not_applied|unknown_code|source_unverified/.test(html));
  assert.match(html, /class="rv-label"[^>]*>실제 사람 응답 0명[^<]*<\/p><p class="rv-question">/);
  // Option percentage bars must be demoted inside a collapsed <details> ("참고용 내부 지표"), not on the default screen.
  assert.doesNotMatch(html, /class="rv-question">[^<]*<\/p><ol class="rv-bars/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/);
  assert.match(html, /<details class="rv-more rv-internal-metrics"><summary>참고용 내부 지표[^<]*<\/summary>.*?<ol class="rv-bars/);
  assert.equal((html.match(/비교 검증에 필요한 조건이 아직 확인되지 않았습니다/g) ?? []).length, state === 'legacy' ? 0 : 1);
  const copy = html.match(/<div class="rv-copy">.*?<span class="rv-muted">(.*?)<\/span>/)[1];
  assert.ok(copy.startsWith('※ 실제 사람 응답 0명(합성 인물 100명 기반 현장 질문·대상 탐색, 실제 여론조사 아님). '));
  assert.ok(!copy.includes('60%'));
  assert.ok(copy.endsWith(hasBaseline && name !== 'mismatch' && name !== 'null_mean'
    ? '이 문항의 오차 범위는 아닙니다.' : '실측 비교 검증 전이며 실제 조사로 확인이 필요합니다.'));
  assert.ok(!/출처|속성 보완|기준선|확인되지/.test(copy));
  assert.ok(html.includes('이 문항의 오차 범위가 아닙니다'));
  if (name === 'unverified') { assert.ok(html.includes('보완 여부와 검증 상태를 확인할 수 없습니다')); assert.ok(!html.includes('속성 보완 미적용')); }
  if (name === 'mismatch') { assert.ok(html.includes('모델판이 달라')); assert.ok(!html.includes('2.5%p')); }
  if (name === 'zero') assert.ok(html.includes('평균 절대 차이 0%p'));
  if (name === 'verified') assert.ok(html.includes('비교 문항 평균 절대 차이 2.5%p') && !html.includes('99%p'));
  if (name === 'partial') assert.ok(html.includes('비교 문항 평균 절대 차이 2.5%p') && !html.includes('null%p'));
  if (name === 'null_mean') assert.ok(html.includes('평균 절대 차이는 미산출'));
  if (baseline) assert.ok(html.includes('성별·성인 교차 통계'));
  if (state !== 'legacy') assert.ok(html.includes('공식 자료의 출처 검증이 완료되지 않았습니다'));
  console.log(`PASS ${name}`);
}
console.log('9/9 render scenarios passed (not browser E2E)');
