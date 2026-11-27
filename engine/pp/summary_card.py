"""Deterministic, bounded first-screen cards; no additional model calls."""
from __future__ import annotations

from . import attribution, public_rules

MAX_CHARS = 3000
SAVE_NOTICE = ('서버를 재시작하면 작업 ID와 결과가 사라집니다. 저장하려면 '
               'save_review(id, path="result.json")을 호출하세요(서버 컴퓨터의 새 파일). '
               '전체 결과·영수증·실행 기록은 get_run(id, view="full")로 조회하세요.')


def clip(value, limit=180):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def build(result: dict, run_id: str) -> dict:
    """Join existing clause/issue/question fields, keeping their source order."""
    warnings = list(result.get('warnings', []))
    cards = []
    issues = {row['id']: row for row in result.get('issues', [])}
    for row in result.get('who_to_ask', [])[:3]:
        iid = row.get('issue_id')
        clauses = [c for c in result.get('clauses', []) if iid in c.get('issues', [])]
        groups = row.get('groups', [])[:3]
        contacts = [o for o in result.get('outreach', []) if o.get('group') in groups][:2]
        cards.append({'issue_id': iid, 'groups': [clip(g, 65) for g in groups],
                      'clause_ids': [c['id'] for c in clauses[:2]],
                      'source_quote': (clauses[0].get('text') or '')[:160] if clauses else None,
                      'why_ask': clip(issues.get(iid, {}).get('summary') or row.get('basis'), 120),
                      'questions': [clip(q, 150) for q in row.get('questions', [])[:2]],
                      'contact_hints': [clip(o.get('where') or o.get('method'), 100) for o in contacts]})
    missing = [{'group': clip(m.get('group') or m.get('segment_id') or m.get('kind'), 60),
                'reason': clip(m.get('reason'), 100)} for m in result.get('missing_perspectives', [])[:4]]
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
    credit = attribution.short(result['attribution']) if result.get('attribution') else '출처·이용 조건은 전체 결과에서 확인하세요.'
    lines = [public_rules.NOTICE, '현장에서 확인할 질문 초안', quality, '찾아갈 곳 · 먼저 물을 질문']
    for card in cards:
        lines.append('• ' + (' · '.join(card['groups']) or '확인할 집단 정보 없음'))
        if card['source_quote']:
            lines.append('  문안 근거(일부): ' + card['source_quote'])
        lines.append('  확인할 이유: ' + card['why_ask'])
        lines += ['  질문: ' + q for q in card['questions']]
        lines += ['  접점 제안(협조 여부 미확인): ' + c for c in card['contact_hints']]
    if not cards:
        lines.append('연결된 질문이 없습니다. 전체 결과의 쟁점과 조항을 확인하세요.')
    lines.append('명단 밖 사람 · 빠진 관점')
    lines += ['• ' + m['group'] + ': ' + m['reason'] for m in missing]
    lines.append('집단 순서는 의견의 강도나 인원 순위가 아닙니다. 접점이 없는 집단은 현장에서 연결 경로를 확인하세요.')
    footer = '\n'.join([clip(w, 160) for w in warnings[:2]] + [credit, SAVE_NOTICE])
    body = '\n'.join(lines)
    available = MAX_CHARS - len(footer) - 2
    text = body[:available] + ('…' if len(body) > available else '') + '\n' + footer
    return {'schema': 'pp.summary/1', 'run_id': run_id, 'cards': cards,
            'missing_perspectives': missing, 'result_quality': quality,
            'truncated': len(result.get('who_to_ask', [])) > 3 or len(result.get('missing_perspectives', [])) > 4 or len(body) > available,
            'text': text, 'attribution_summary': credit, 'full_result_available': True,
            'save_notice': SAVE_NOTICE}


def response(state: dict) -> dict:
    """Do not leak large receipts into the default MCP response."""
    data = {k: state[k] for k in ('notice', 'id', 'status', 'stage', 'stage_label', 'progress', 'estimated_remaining_seconds',
                                  'poll_after_ms', 'error') if k in state}
    if state.get('status') == 'completed':
        data['summary'] = build(state['result'], state['id'])
        data['save_notice'] = SAVE_NOTICE
    return data
