"""Reviewed historical diagnostics, separate from a model-matched baseline-v2.

A snapshot is attached only to new original-panel results. It is never an
independent accuracy validation or permission to activate enrichment.
"""
from pathlib import Path
import math
import statistics

from .persona_accuracy import DATA, file_hash, read_json, verified_sources

PATH = DATA / 'historical-baseline-2024.json'
QUESTIONS = {'marriage', 'remarriage', 'safety_crime', 'safety_disaster', 'safety_security'}


def checked_bundle(path: Path) -> dict:
    bundle = read_json(path)
    if bundle['kind'] != 'historical-diagnostic-v1':
        raise ValueError('not_historical_diagnostic')
    artifacts = {}
    for name, digest in bundle['artifacts'].items():
        if Path(name).name != name or file_hash(path.parent / name) != digest:
            raise ValueError('artifact_hash_mismatch')
        artifacts[name] = read_json(path.parent / name)
    forward = artifacts['comparison-2024.json']
    reverse = artifacts['comparison-2024-reversed.json']
    sources = verified_sources(artifacts['sources-reviewed.json'])
    if not QUESTIONS | {'population-2024'} <= sources.keys():
        raise ValueError('source_unverified')
    if any(s['period'] != '2024' or s['unit'] != 'adult_person' or not s['evidence']
           for s in sources.values()):
        raise ValueError('source_scope_or_evidence_missing')
    run = artifacts['measured-run.json']
    if (run['status'] != 'complete' or run['attempts'] != 30000 or run['n'] != 3000
            or run['seed'] != 2024 or run['failures'] / run['attempts'] > .01
            or run['cost_usd'] > 1.5 or len(run['returned_models']) != 1):
        raise ValueError('run_incomplete')
    model = run['returned_models'][0]
    for comparison in (forward, reverse):
        if (comparison['status'] != 'diagnostic_complete' or comparison['model_version'] != model
                or {i['id'] for i in comparison['items']} != QUESTIONS or len(comparison['items']) != 5):
            raise ValueError('comparison_incomplete')
        for name, filename in {'official':'official-2024.json', 'weights':'frozen-weights.json',
                               'sources':'sources-reviewed.json'}.items():
            if comparison['input_hashes'][name] != run['input_hashes'][filename]:
                raise ValueError('input_hash_mismatch')
        if comparison['input_hashes']['sources'] != bundle['artifacts']['sources-reviewed.json']:
            raise ValueError('source_hash_mismatch')
        for item in comparison['items']:
            if item['min_age'] != 20 or item['year'] != 2024 or item['unit'] != 'adult_person':
                raise ValueError('scope_mismatch')
            if (not item['eligible'] or not item['sex_eligible'] or item['n_planned'] != 3000
                    or item['n_adult_planned'] != run['adult_n']
                    or item['n_adult_answered'] < .99 * run['adult_n']):
                raise ValueError('paired_responses_incomplete')
            for key in ('mae_overall_pp', 'worst_pp', 'mae_sex_pp'):
                if not isinstance(item[key], (int,float)) or not math.isfinite(item[key]) or not 0 <= item[key] <= 100:
                    raise ValueError('metrics_incomplete')
            # Recompute headline metrics from the saved standardized vectors.
            gaps = [100*abs(a-b) for a,b in zip(item['official_overall'],item['synthetic_overall'])]
            if (len(gaps) != len(item['options']) or abs(statistics.mean(gaps)-item['mae_overall_pp'])>1e-9
                    or abs(max(gaps)-item['worst_pp'])>1e-9):
                raise ValueError('metrics_mismatch')
        if abs(statistics.mean(i['mae_overall_pp'] for i in comparison['items'])-comparison['mae_pp'])>1e-9:
            raise ValueError('summary_mismatch')
    if (forward['input_hashes']['paired_responses'] != reverse['input_hashes']['responses']
            or reverse['input_hashes']['paired_responses'] != forward['input_hashes']['responses']):
        raise ValueError('pair_mismatch')
    scope = {k:forward['items'][0][k] for k in ('year','unit','population','min_age','max_age')}
    return dict(status='verified', evaluation_kind='historical_diagnostic',
        mae_pp=round(forward['mae_pp'],1), worst_pp=round(forward['worst_pp'],1),
        question_ids=[i['id'] for i in forward['items']], scope=scope,
        inputs={'model':{'model_revision':model}}, panel_version=run['panel_version'],
        source='2024 사회조사', model_identity_verified=False,
        reverse_mae_pp=round(reverse['mae_pp'],1),
        unsure_signed_pp=[round(i['unsure_signed_pp'],1) for i in forward['items'] if i['unsure_signed_pp'] is not None],
        excluded_reasons=['historical_development_only','model_identity_unproven','population_standard_caveat'],
        artifact_hash=file_hash(path))


def load(path: Path = PATH) -> dict | None:
    try:
        return checked_bundle(path)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return None
