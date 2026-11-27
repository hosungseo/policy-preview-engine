// Server-render checks for core principle alignment & ServiceGate / modelGuide guards.
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
    jsc: {
      parser: { syntax: 'typescript', tsx: file.endsWith('.tsx') },
      target: 'es2022', transform: { react: { runtime: 'automatic' } },
    },
  });
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, require: (name) => overrides[name] ?? require(name) });
  return module.exports;
}

const format = load('src/lib/format.ts');
const colors = load('src/lib/colors.ts');
const modelGuide = load('src/lib/modelGuide.ts');
const ModelBadge = load('src/components/review/ModelBadge.tsx', {
  '@/lib/modelGuide': modelGuide,
}).default;
const PersonaCard = load('src/components/PersonaCard.tsx', {
  '@/lib/colors': colors,
  '@/lib/format': format,
  './SupportBadge': { __esModule: true, default: () => null },
  './components.css': {},
}).default;
const HearingReads = load('src/components/HearingReads.tsx', {
  '@/lib/colors': colors,
  '@/lib/format': format,
  './StatTile': { __esModule: true, default: () => null },
  './components.css': {},
}).default;

// 1. modelGuide withdraws all "발표 전/비공개 문안 입력 가능" claims across every profile.
for (const kind of ['global', 'korean', 'local', 'mock', 'mixed']) {
  const profile = {
    kind, label: kind, use: '',
    sentence: { name: 'S', where: kind === 'korean' ? 'korean' : 'global' },
    decision: { name: 'D', where: kind === 'korean' ? 'korean' : 'global' },
    choices: [],
  };
  const longText = modelGuide.inputGuide(profile);
  const shortText = modelGuide.shortGuide(profile);
  for (const text of [longText, shortText]) {
    assert.ok(!/발표 전 정책안|내부 검토안까지|민감 S|기밀 C/.test(text), `forbidden guide text for ${kind}: ${text}`);
  }
  if (kind !== 'mock') {
    assert.ok(longText.includes('공개') && longText.includes('발표 전 비공개 문안'), `missing public-only warning for ${kind}`);
  }
}
console.log('PASS modelGuide withdraws pre-announcement/private draft guidance');

// 2. ModelBadge renders global endpoint honestly (no N2SF O/S/C permission text).
const badgeHtml = renderToStaticMarkup(React.createElement(ModelBadge, {
  profile: {
    kind: 'mixed', label: '혼합 구성', use: '공개 문안만',
    sentence: { name: 'LG EXAONE k-exaone_v2.5', where: 'korean' },
    decision: { name: 'Upstage Solar Decide (solar-decide · 글로벌)', where: 'global' },
    choices: [{ kind: 'global', label: '해외 모델', use: '공개 문안만' }],
  },
}));
assert.ok(badgeHtml.includes('해외 API') && !badgeHtml.includes('국가 망 보안체계') && !badgeHtml.includes('찬반 확률'));
console.log('PASS ModelBadge renders honest region and public-only guidance');

// 3. Synthetic real names are never displayed in PersonaCard, HearingReads, or format helpers.
const person = {
  uuid: 'u1', panel: 'rep', found_by: [], name: '민시온', sex: '여자', age: 42, age_band: '40대',
  province: '서울', region: '수도권', district: '서울-강남구', occupation: '사무원',
  occupation_major: '사무 종사자', education_level: '4년제 대학교', marital_status: '미혼',
  family_type: '혼자 거주', family: '1인 가구', housing_type: '아파트',
  summary: '', detail: '', similar: [],
};
assert.ok(!format.personaShort(person).includes('민시온'));
assert.equal(format.stripPersonaName('박준환 씨는 춘천의 거리에서 일합니다.'), '이 합성 인물은 춘천의 거리에서 일합니다.');

const cardHtml = renderToStaticMarkup(React.createElement(PersonaCard, {
  person,
  reaction: { rid: 'r1', uuid: 'u1', support: 0, impact: '직접', trigger_quote: '', quote_verified: false, reason: '이유입니다.', concerns: [], hopes: [], suggestion: '', would_comment: false, channel: '' },
  similar: [{ ...person, uuid: 'u2', name: '김철수' }],
}));
assert.ok(!cardHtml.includes('민시온') && !cardHtml.includes('김철수'));
assert.ok(cardHtml.includes('합성 인물') && cardHtml.includes('40대'));

const readsHtml = renderToStaticMarkup(React.createElement(HearingReads, {
  hearing: {
    participants: ['u1'],
    agenda: [],
    turns: [],
    summary: { agreements: [], disagreements: [], missing: [] },
    reads: [{ index: 1, round: 1, speaker: 'u1', stance: 0, marks: {} }],
    trajectories: { participants: [{ uuid: 'u1', stances: { '1': 0 }, change: 0 }], movers: [], counts: {}, move: 0.5 },
  },
  person: new Map([['u1', person]]),
}));
assert.ok(!readsHtml.includes('민시온') && readsHtml.includes('합성 참석자 1'));
console.log('PASS PersonaCard, HearingReads, and format helpers anonymize synthetic names');

// 4. SurveyList source does not render headline percentage.
const surveyListSrc = readFileSync('src/components/review/SurveyList.tsx', 'utf8');
assert.ok(!surveyListSrc.includes('headline.percent') && !surveyListSrc.includes('발표 전에 정책을'));
const serviceGateSrc = readFileSync('src/components/review/ServiceGate.tsx', 'utf8');
assert.ok(serviceGateSrc.includes('state: "error"') && serviceGateSrc.includes('panel_missing'));
console.log('PASS SurveyList removes headline percent and ServiceGate distinguishes server errors');
