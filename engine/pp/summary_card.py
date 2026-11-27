"""Deterministic, bounded first-screen cards; no additional model calls.

Display order: notices → numbers (scale, shares, wobble, not-opinion banner) → group table →
places to visit, each with its numeric evidence → people outside the roster. Numbers appear only
when the result carries the engine's aggregate fields; their wording lives in numbers_copy.
"""
from __future__ import annotations

from . import attribution, numbers_copy, public_rules

MAX_CHARS = 3000
NO_CONTACT = '해당 집단의 찾아갈 곳 자료 없음'
SAVE_NOTICE = ('작업 번호: {run_id}. 재시작하면 결과가 사라집니다. '
               '“이 결과를 저장해 줘” 또는 “이 작업의 전체 결과를 보여 줘”라고 말하세요. '
               '저장 위치: Documents/백번미리묻다.')
MORE_NUMBERS = '숫자 더 보기(0원): "60대만 보면?"처럼 물으면 이 결과를 다시 잘라 봅니다.'


def clip(value, limit=180):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _matches(highlight: dict, row: dict) -> bool:
    groups = set(row.get('groups') or [])
    return bool((highlight.get('issue_id') and highlight['issue_id'] == row.get('issue_id'))
                or groups & set(highlight.get('groups') or []) or highlight.get('label') in groups)


def _joined(*sections) -> str:
    return '\n'.join(line for section in sections for line in section)


def _clip_lines(lines: list[str], budget: int) -> list[str]:
    text = '\n'.join(lines)
    if len(text) <= budget:
        return lines
    return [text[:budget - 1] + '…'] if budget > 1 else []


def build(result: dict, run_id: str) -> dict:
    """Join existing clause/issue/question fields, keeping their source order."""
    warnings = list(result.get('warnings', []))
    numbers = numbers_copy.view(result)
    save_notice = SAVE_NOTICE.format(run_id=run_id)
    # Numbers take the top of the card, so clause excerpts get shorter to keep every card inside the limit.
    quote_limit = 60 if numbers else 160
    cards = []
    issues = {row['id']: row for row in result.get('issues', [])}
    rows = result.get('who_to_ask', [])[:3]
    for row in rows:
        iid = row.get('issue_id')
        clauses = [c for c in result.get('clauses', []) if iid in c.get('issues', [])]
        if row.get('clause_ids'):
            clause_order = {cid: n for n, cid in enumerate(row['clause_ids'])}
            clauses.sort(key=lambda clause: clause_order.get(clause['id'], len(clause_order)))
        groups = row.get('groups', [])[:3]
        contacts = [o for o in result.get('outreach', []) if o.get('group') in groups][:2]
        cards.append({'issue_id': iid, 'groups': [clip(g, 65) for g in groups],
                      'clause_ids': [c['id'] for c in clauses[:2]],
                      'source_quote': (clauses[0].get('text') or '')[:quote_limit] if clauses else None,
                      'why_ask': clip(issues.get(iid, {}).get('summary') or row.get('basis'), 120),
                      'questions': [clip(q, 150) for q in row.get('questions', [])[:2]],
                      'contact_hints': [clip(v, 100) for v in row.get('venues', [])[:1 if result.get('mode') == 'archived' else 3] if v] or
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

    # Engine aggregates, attached after the prose check: these sentences come from fixed templates.
    candidates = []
    if numbers:
        used = []
        for card, row in zip(cards, rows):
            match = next((h for h in numbers['highlights'] if h not in used and _matches(h, row)), None)
            if match:
                card['numbers_basis'] = numbers_copy.basis_line(match)
                used.append(match)
        for h in [h for h in numbers['highlights'] if h not in used][:2]:
            venue = public_rules.check_output(clip(h['venue'], 80), '', warnings) if h.get('venue') else None
            candidates.append(numbers_copy.candidate_line(h, venue))

    conditions = result.get('conditions', {})
    quality = '일부 생성 실패 또는 인용 미검증: 전체 결과에서 확인하세요.' if (
        conditions.get('reaction_failures') or conditions.get('unverified_quotes')) else '현장 확인이 필요한 AI 초안'
    credit = (result['attribution']['notice'] if result.get('mode') == 'mock' else attribution.short(result['attribution'])) if result.get('attribution') else '출처·이용 조건은 전체 결과에서 확인하세요.'
    trial = {k: result[k] for k in ('mode', 'result_label', 'trial_notice') if k in result}
    head = [numbers_copy.BANNER] if numbers else ([trial['trial_notice'], public_rules.NOTICE, trial.get('result_label', '')] if result.get('mode') == 'mock'
            else [public_rules.NOTICE, *[str(trial[k]) for k in ('result_label', 'trial_notice') if k in trial]])
    if result.get('archive'):
        archive = result['archive']
        head.append('보관 출처: ' + archive['created_at'][:10] + ' 기록(경로·해시는 전체 결과)')

    top, slices, affected = [], [], []
    if numbers:
        # One fixed banner opens the card; keep just the situation-specific tail here.
        top = numbers_copy.top_lines(numbers)
        top.remove(numbers_copy.BANNER)
        line = numbers_copy.affected_line(numbers)
        affected = [line] if line else []
        slices = ([numbers_copy.SLICE_HEAD] + [numbers_copy.slice_text(s, numbers, warnings) for s in numbers['slices'][-3:]]
                  if numbers['slices'] else [])
        slices.append(MORE_NUMBERS)
    # Table sizes to try, largest first: every row, then age bands plus marked cells.
    tables = ([numbers_copy.table_lines(numbers), numbers_copy.table_lines(numbers, numbers_copy.compact_rows(numbers))]
              if numbers else [[]])
    table = tables[0] + affected

    places = ['현장에서 확인할 질문 초안', quality, '찾아갈 곳 · 먼저 물을 질문']
    if result.get('mode') == 'archived':
        places.append('확인할 이유: 보관 결과의 AI 요약, 위 숫자와 다를 수 있음')
    for card in cards:
        places.append('• ' + (' · '.join(card['groups']) or '확인할 집단 정보 없음'))
        if card.get('numbers_basis'):
            places.append('  ' + card['numbers_basis'])
        if card['source_quote']:
            places.append('  문안 근거(일부): ' + card['source_quote'])
        places.append('  확인할 이유: ' + card['why_ask'])
        places += ['  먼저 물을 질문' + ('(편집 초안)' if card.get('reaction_quotes') else '') + ': ' + q for q in card['questions']]
        places += ['  보관 결과 인용: ' + q for q in card.get('reaction_quotes', [])]
        places += [('  찾아갈 곳: ' if c == NO_CONTACT else '  찾아갈 곳·방식(협조 여부 미확인): ') + c for c in card['contact_hints']]
    if not cards:
        places.append('연결된 질문이 없습니다. 전체 결과의 쟁점과 조항을 확인하세요.')
    # Visit candidates come from the numbers, so card prose is clipped before they are.
    leads = [numbers_copy.CANDIDATES_HEAD, *candidates] if candidates else []
    outside = ['명단 밖 사람 · 빠진 관점']
    outside += ['• ' + m['group'] + ': ' + m['reason'] + (' · ' + m['route'] if m['route'] else '') for m in missing]
    outside.append('집단 순서는 의견의 강도나 인원 순위가 아닙니다. 접점이 없는 집단은 현장에서 연결 경로를 확인하세요.')

    footer = '\n'.join([clip(w, 160) for w in warnings[:2]] + [credit, save_notice])
    available = MAX_CHARS - len(footer) - 2

    def size():
        return len(_joined(head, top, table, slices, places, leads, outside))

    # Shrink in a fixed order: earlier re-aggregations, then table rows, then the end of the card prose.
    # The numbers block, the table head, the visit candidates and the off-roster section always stay.
    shrunk = False
    if size() > available and len(slices) > 1:
        slices, shrunk = [MORE_NUMBERS], True
    for smaller in tables[1:]:
        if size() <= available:
            break
        table, shrunk = smaller + ['(지면을 줄여 연령대와 강조 집단만 표시했습니다. 권역·성별은 다시 자르거나 전체 결과에서 확인하세요.)'] + affected, True
    if size() > available:
        places, shrunk = _clip_lines(places, available - len(_joined(head, top, table, slices, leads, outside)) - 1), True
    body = _joined(head, top, table, slices, places, leads, outside)
    if len(body) > available:
        body, shrunk = body[:available - 1] + '…', True
    text = body + '\n' + footer
    return {'schema': 'pp.summary/1', 'run_id': run_id, 'cards': cards,
            **{k: ({field: value for field, value in result[k].items() if field != 'distribution_selection'} if k == 'overall' else result[k])
               for k in ('numeric_notice', 'overall', 'by_group', 'highlights', 'baseline') if k in result},
            'missing_perspectives': missing, 'grouping': result.get('grouping', {}), **trial, 'result_quality': quality,
            'truncated': len(result.get('who_to_ask', [])) > 3 or len(result.get('missing_perspectives', [])) > 4 or shrunk,
            'text': text, 'attribution_summary': credit, 'full_result_available': True,
            **({'numbers': numbers} if numbers else {}),
            **({'archive': result['archive'], 'policy_source': result.get('policy_source')} if result.get('archive') else {}),
            'save_notice': save_notice}


def response(state: dict) -> dict:
    """Do not leak large receipts into the default MCP response."""
    data = {k: state[k] for k in ('notice', 'id', 'status', 'stage', 'stage_label', 'progress', 'estimated_remaining_seconds',
                                  'poll_after_ms', 'cost_usd', 'example', 'available_examples', 'mode', 'result_label', 'trial_notice', 'error', 'code', 'error_code', 'message', 'next_action', 'free_alternative', 'retryable') if k in state}
    if state.get('status') == 'completed':
        data['summary'] = build(state['result'], state['id'])
        data.update({k: state['result'][k] for k in ('mode', 'result_label', 'trial_notice') if k in state['result']})
        data['save_notice'] = SAVE_NOTICE.format(run_id=state['id'])
    return data
