// Render the actual completed deep summary with deliberately different panel counts.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import swc from 'next/dist/build/swc/index.js';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const { code } = swc.transformSync(readFileSync('src/components/review/DeepView.tsx', 'utf8'), {
  filename: 'DeepView.tsx', module: { type: 'commonjs' },
  jsc: { parser: { syntax: 'typescript', tsx: true }, target: 'es2022',
    transform: { react: { runtime: 'automatic' } } },
});
const module = { exports: {} };
vm.runInNewContext(code + '\nmodule.exports.Completed = Done;', {
  module, exports: module.exports,
  require: name => name === '@/lib/reviewApi' ? {} : require(name),
});
const result = {
  mock: false, counts: { matched: 3, affected: 9, heard: 12 }, by_option: [],
  issues: [{ id: 'one', title: '대표 쟁점', n: 1, summary: '시험', quotes: [],
    by_panel: { rep: { n: 1 }, aff: { n: 9 } } }],
  outreach: [{ kind: '직업', group: '시험 집단', n: 9, panel: 'aff', suggestion: null }],
  alternatives: [], qa: [], limits: [], fallbacks: [],
  hearing: { participants: 0, turns: 0, summary: null }, seconds: 1, cost_usd: 0,
};
const html = renderToStaticMarkup(React.createElement(module.exports.Completed, { r: result }));
assert.match(html, /대표 패널 1명/);
assert.match(html, /영향권 9명 \(전체 비율로 읽지 않음\)/);
assert.match(html, /영향권: 전체 비율로 읽지 않음/);
assert.ok(!html.includes('들은 사람 중'));
console.log('PASS representative and affected counts render separately');
