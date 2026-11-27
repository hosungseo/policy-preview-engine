"""Deterministic, bounded first-screen cards; no additional model calls."""
from __future__ import annotations

from . import attribution, public_rules

MAX_CHARS = 3000
NO_CONTACT = '해당 집단의 찾아갈 곳 자료 없음'
SAVE_NOTICE = ('서버를 재시작하면 작업 ID와 결과가 사라집니다. 저장하려면 '
               'save_review(id)를 호출하세요(홈의 Documents/백번미리묻다에 저장). '
               '전체 결과·영수증·실행 기록은 get_run(id, view="full")로 조회하세요.')


def clip(value, limit=180):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def rate_text(rate):
    if 0 < rate < .001:
        return '<0.1%'
    if .999 < rate < 1:
        return '>99.9%'
    return f'{rate * 100:.1f}%'


def build(result: dict, run_id: str) -> dict:
    """Join existing clause/issue/question fields, keeping their source order."""
    warnings = list(result.get('warnings', []))
    cards = []
    issues = {row['id']: row for row in result.get('issues', [])}
    for row in result.get('who_to_ask', [])[:3]:
        iid = row.get('issue_id')
        clauses = [c for c in result.get('clauses', []) if iid in c.get('issues', [])]
        if row.get('clause_ids'):
            clause_order = {cid: n for n, cid in enumerate(row['clause_ids'])}
            clauses.sort(key=lambda clause: clause_order.get(clause['id'], len(clause_order)))
        groups = row.get('groups', [])[:3]
        contacts = [o for o in result.get('outreach', []) if o.get('group') in groups][:2]
        cards.append({'issue_id': iid, 'groups': [clip(g, 65) for g in groups],
                      'clause_ids': [c['id'] for c in clauses[:2]],
                      'source_quote': (clauses[0].get('text') or '')[:160] if clauses else None,
                      'why_ask': clip(issues.get(iid, {}).get('summary') or row.get('basis'), 120),
                      'questions': [clip(q, 150) for q in row.get('questions', [])[:2]],
                      'contact_hints': [clip(v, 100) for v in row.get('venues', [])[:3] if v] or
                          [clip(' · '.join(filter(None, (o.get('where'), o.get('method')))), 100) for o in contacts if o.get('where') or o.get('method')] or [NO_CONTACT],
                      **({'reaction_quotes': row['reaction_quotes'][:1], 'question_basis': row['question_basis']} if row.get('reaction_quotes') else {}),
                      'panel_scope': row.get('panel_scope')})
    missing = [{'group': clip(m.get('group') or m.get('segment_id') or m.get('kind'), 60),
                'reason': clip(m.get('reason'), 100), 'route': clip(m.get('route'), 100)} for m in result.get('missing_perspectives', [])[:4]]
    # Apply the same prose rules as the full public output; source_quote is already public text.
    source_text = '\n'.join(c.get('text', '') for c in result.get('clauses', []))
    # Recheck excerpts as source text, so legal ages and other policy numbers survive.
    for card in cards:
        quote = card.pop('source_quote')
        checked = public_rules.check_output(card, '', warnings)
        card.clear()
        card.update(checked)
        card['source_quote'] = public_rules.check_output(quote, source_text, warnings, field='trigger_quote') if quote else None
    missing = public_rules.check_output(missing, '', warnings)
    conditions = result.get('conditions', {})
    quality = '일부 생성 실패 또는 인용 미검증: 전체 결과에서 확인하세요.' if (
        conditions.get('reaction_failures') or conditions.get('unverified_quotes')) else '현장 확인이 필요한 AI 초안'
    credit = (result['attribution']['notice'] if result.get('mode') == 'mock' else attribution.short(result['attribution'])) if result.get('attribution') else '출처·이용 조건은 전체 결과에서 확인하세요.'
    trial = {k: result[k] for k in ('mode', 'result_label', 'trial_notice') if k in result}
    lines = ([trial['trial_notice'], public_rules.NOTICE, trial.get('result_label', '')] if result.get('mode') == 'mock'
             else [public_rules.NOTICE, *[str(trial[k]) for k in ('result_label', 'trial_notice') if k in trial]])
    if result.get('archive'):
        archive = result['archive']
        lines.append('보관 출처: ' + archive['path'] + ' · ' + archive['created_at'])
    overall = result.get('overall')
    if overall:
        lines.insert(1, result.get('numeric_notice', public_rules.NOTICE))
        lines.append(f"대표 합성 인물 {overall['n']:,}명 · 이유 수집 {overall.get('reason_sample_n', 0):,}명(별도)")
        if overall.get('rates'):
            rates = overall['rates']
            lines.append('모의 분포: ' + ' · '.join(f'{label} {rate_text(rates[key])}' for key, label in (('support', '찬성 쪽'), ('oppose', '반대 쪽'), ('unknown', '모름·유보'))))
        wobble = overall.get('variability', {})
        lines.append(f"흔들림 폭 ±{wobble['width_pp']:.1f}%p (대조 문장·순서 기준)" if wobble.get('available') else '흔들림 폭 미측정')
        if wobble.get('unstable'):
            lines.append(wobble['notice'])
        decision = overall.get('decision') or {}
        if decision.get('fallback'):
            lines.append(decision['notice'])
    lines += ['현장에서 확인할 질문 초안', quality, '찾아갈 곳 · 먼저 물을 질문']
    for card in cards:
        lines.append('• ' + (' · '.join(card['groups']) or '확인할 집단 정보 없음'))
        if card['source_quote']:
            lines.append('  문안 근거(일부): ' + card['source_quote'])
        lines.append('  확인할 이유: ' + card['why_ask'])
        lines += ['  먼저 물을 질문' + ('(편집 초안)' if card.get('reaction_quotes') else '') + ': ' + q for q in card['questions']]
        lines += ['  보관 결과 인용: ' + q for q in card.get('reaction_quotes', [])]
        lines += [('  찾아갈 곳: ' if c == NO_CONTACT else '  찾아갈 곳·방식(협조 여부 미확인): ') + c for c in card['contact_hints']]
    if not cards:
        lines.append('연결된 질문이 없습니다. 전체 결과의 쟁점과 조항을 확인하세요.')
    lines.append('명단 밖 사람 · 빠진 관점')
    lines += ['• ' + m['group'] + ': ' + m['reason'] + (' · ' + m['route'] if m['route'] else '') for m in missing]
    lines.append('집단 순서는 의견의 강도나 인원 순위가 아닙니다. 접점이 없는 집단은 현장에서 연결 경로를 확인하세요.')
    footer = '\n'.join([clip(w, 160) for w in warnings[:2]] + [credit, SAVE_NOTICE])
    body = '\n'.join(lines)
    available = MAX_CHARS - len(footer) - 2
    text = body[:available] + ('…' if len(body) > available else '') + '\n' + footer
    return {'schema': 'pp.summary/1', 'run_id': run_id, 'cards': cards,
            **{k: ({field: value for field, value in result[k].items() if field != 'distribution_selection'} if k == 'overall' else result[k])
               for k in ('numeric_notice', 'overall', 'by_group', 'highlights', 'baseline') if k in result},
            'missing_perspectives': missing, 'grouping': result.get('grouping', {}), **trial, 'result_quality': quality,
            'truncated': len(result.get('who_to_ask', [])) > 3 or len(result.get('missing_perspectives', [])) > 4 or len(body) > available,
            'text': text, 'attribution_summary': credit, 'full_result_available': True,
            **({'archive': result['archive'], 'policy_source': result.get('policy_source')} if result.get('archive') else {}),
            'save_notice': SAVE_NOTICE}


def response(state: dict) -> dict:
    """Do not leak large receipts into the default MCP response."""
    data = {k: state[k] for k in ('notice', 'id', 'status', 'stage', 'stage_label', 'progress', 'estimated_remaining_seconds',
                                  'poll_after_ms', 'cost_usd', 'example', 'available_examples', 'mode', 'result_label', 'trial_notice', 'error', 'code', 'error_code', 'message', 'next_action', 'free_alternative', 'retryable') if k in state}
    if state.get('status') == 'completed':
        data['summary'] = build(state['result'], state['id'])
        data.update({k: state['result'][k] for k in ('mode', 'result_label', 'trial_notice') if k in state['result']})
        data['save_notice'] = SAVE_NOTICE
    return data
