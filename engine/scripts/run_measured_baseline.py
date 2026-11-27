"""Budget-bounded real Jev diagnostic with durable per-call records and no retries."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pp import jev
from ppservice.persona_accuracy import canonical,read_json,file_hash
from ppservice.survey import panel
from ppservice.survey.run import state_for,jev_questions,option_keys,estimate_tokens

PRICE=.042/1_000_000
# Published default per-request context is 64k; reserve 65,536 billable tokens
# per in-flight or unknown request, never use average estimates as a hard bound.
RESERVE=65536*PRICE
CAP=1.5

def run(directory,execute=False):
    official=read_json(directory/'official-2024.json')
    all_people,version=panel.load(addons="off"); people=panel.sample(all_people,3000,2024)
    specs={i['id']:{k:i[k] for k in ('title','question','options')} for i in official['items']}
    for s in specs.values():s['policy_text']='(이 문항은 특정 정책에 관한 것이 아닙니다.)'
    estimate=sum(estimate_tokens(s,len(p['profile'])) for s in specs.values() for p in people)*PRICE
    arms=['main','reversed'] if estimate*2<=CAP else ['main']
    tasks=[(arm,q,p) for q in specs for p in people for arm in arms]
    manifest=dict(started_at=datetime.now(timezone.utc).isoformat(),seed=2024,n=3000,adult_n=sum(p['age']>=20 for p in people),panel_version=version,price_per_million=.042,price_url='https://docs.typesafe.ai/models',cap_usd=CAP,forward_estimate_usd=estimate,both_estimate_usd=2*estimate,arms=arms,planned_calls=len(tasks),requested_model='jev-1.14.0',immutable_revision_proven=False,input_hashes={f:file_hash(directory/f) for f in ['official-2024.json','frozen-weights.json','sources-reviewed.json']},status='estimated')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)
    if not execute:return
    os.environ['PP_JEV_PROVIDER']='api';os.environ['PP_JEV_MODEL']='jev-1.14.0'
    if not jev.api_key():raise SystemExit('API key unavailable')
    logpath=directory/'answers.jsonl'
    if logpath.exists():raise SystemExit('Existing run: refuse repeat billing')
    records=[];cost=0.;failed=0;started=time.monotonic();stop=None
    def one(t):
        arm,q,p=t;s=specs[q]
        state=state_for(arm,s,p);questions=jev_questions(s['options'],arm=='reversed')
        body=dict(state=state,model=jev.model(),questions=questions)
        row=dict(arm=arm,question_id=q,uuid=p['uuid'],request_sha256=hashlib.sha256(canonical(body)).hexdigest())
        try:
            out=jev.evaluate(state,questions,cache=False,retries=0,label='measured-baseline')
            row.update(model=out.get('model'),usage=out.get('usage'),raw_probabilities=out['answers']['q']['probabilities'])
            vals=[float(row['raw_probabilities'][k]) for k in option_keys(s['options'])]
            if any(not math.isfinite(v) or v<0 for v in vals) or sum(vals)<=0:raise ValueError('probabilities')
            if not isinstance(row['usage']['input_tokens'],int) or not 0<=row['usage']['input_tokens']<=65536:raise ValueError('usage')
            if row['model']!='jev-1.14.0':raise ValueError('model_changed')
            row.update(probabilities=[v/sum(vals) for v in vals],status='ok')
        except Exception as e:
            row.update(status='failed',error_type=type(e).__name__)
        return row
    with logpath.open('x') as log, ThreadPoolExecutor(max_workers=24) as pool:
        for start in range(0,len(tasks),24):
            chunk=tasks[start:start+24]
            if cost+len(chunk)*RESERVE>CAP:stop='budget_cap';break
            # Persist reservation before transmission; interrupted requests stay fully reserved.
            (directory/'inflight.json').write_bytes(canonical(dict(start=start,reserved_usd=len(chunk)*RESERVE,settled_usd=cost)))
            for row in pool.map(one,chunk):
                log.write(canonical(row).decode());log.flush();os.fsync(log.fileno());records.append(row)
                tokens=(row.get('usage') or {}).get('input_tokens')
                charged=tokens*PRICE if isinstance(tokens,int) and 0<=tokens<=65536 else RESERVE
                row['charged_usd']=charged;cost+=charged
                failed+=row['status']!='ok'
            (directory/'inflight.json').write_bytes(canonical(dict(start=start+len(chunk),reserved_usd=0,settled_usd=cost)))
            manifest.update(attempts=len(records),failures=failed,cost_usd=cost,elapsed_seconds=time.monotonic()-started)
            (directory/'run-manifest.json').write_bytes(canonical(manifest))
            if len(records)%240==0:print(json.dumps({k:manifest[k] for k in ['attempts','failures','cost_usd','elapsed_seconds']}),flush=True)
            if failed/len(records)>.01:stop='failure_rate_over_1_percent';break
            if cost>CAP:stop='budget_bound_failed';break
    models=sorted({r.get('model') for r in records if r.get('model')})
    definitions={i['id']:dict(i['definition'],options=i['options']) for i in official['items']}
    for arm in arms:
        answers={q:{} for q in specs}
        for r in records:
            if r['arm']==arm and r['status']=='ok':answers[r['question_id']][r['uuid']]=r['probabilities']
        result=dict(people=[{k:p[k] for k in ['uuid','age','sex']} for p in people],answers=answers,model_version=models[0] if len(models)==1 else None,definitions=definitions,panel_version=version,arm=arm)
        (directory/('responses.json' if arm=='main' else 'responses-reversed.json')).write_bytes(canonical(result))
    manifest.update(status='stopped' if stop else 'complete',stop_reason=stop,returned_models=models,input_tokens=sum((r.get('usage') or {}).get('input_tokens',0) for r in records),output_tokens=sum((r.get('usage') or {}).get('output_tokens',0) for r in records),elapsed_seconds=time.monotonic()-started,finished_at=datetime.now(timezone.utc).isoformat())
    (directory/'run-manifest.json').write_bytes(canonical(manifest));print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);ap.add_argument('--execute',action='store_true');a=ap.parse_args();run(a.directory,a.execute)
