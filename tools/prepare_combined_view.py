"""Build the browser snapshot with distinct real, mutation and historical batches."""
import argparse
import base64
import datetime
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from view_payload import unpack_build_columns, unpack_strings


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def preserve(old_dir, new_dir):
    old = json.load(gzip.open(Path(old_dir)/'collected-data.json.gz', 'rt', encoding='utf-8'))
    new = json.load(gzip.open(Path(new_dir)/'collected-data.json.gz', 'rt', encoding='utf-8'))
    by_id = {r['job_id']: r for r in new['battles']}
    assert all(by_id.get(r['job_id']) == r for r in old['battles'])
    return len(old['battles'])


def prepare(real_dir, mutation_dir, pointer, freeze_previous=False):
    real_dir, mutation_dir = Path(real_dir).resolve(), Path(mutation_dir).resolve()
    previous = read(pointer)
    references = read(previous['label_reference'])
    labels = {b['id']: b['label'] for b in references['builds']}
    old_labels = dict(labels)
    history = [Path(p) for p in previous['comparison_views'] if read(p)['search_budget_ms'] == 2000]
    assert [read(p)['stats']['battles'] for p in history] == [72959, 4856]
    frozen = list(previous.get('frozen_8s_views', []))
    if freeze_previous:
        previous_frozen = []
        for role, source in [('mutation', previous['mutation_view_data']), ('real', previous['view_data'])]:
            path = mutation_dir/f'frozen-8s-{role}.json'
            data = read(source)
            save(path, {**data, 'collection_active': False})
            previous_frozen.append(str(path))
        frozen = list(dict.fromkeys([*previous_frozen, *frozen]))
    history = [*[Path(p) for p in frozen], *history]
    for folder in (real_dir, mutation_dir):
        shutil.copy2(Path(previous['directory'])/'localization.json', folder/'localization.json')
        shutil.copy2('tools/battles_view.html', folder/'candidate.html')
    def run(folder, label, reference, comparisons):
        args = [sys.executable, '-X', 'utf8', 'tools/prepare_snapshot_view.py', '--input-dir', str(folder),
                '--fragment', str(folder/'candidate.html'), '--previous', str(reference),
                '--dataset-label', label, '--standalone']
        for comparison in comparisons: args += ['--comparison-view', str(comparison)]
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
        return read(folder/'view-data.json')
    real = run(real_dir, '真实来源 · 8 秒搜索' + (' · 卡牌状态 v3' if frozen else ''), previous['label_reference'], [])
    labels.update({b['id']: b['label'] for b in real['builds']})
    reference = mutation_dir/'label-reference.json'
    save(reference, {'builds':[{'id':key,'label':label} for key,label in labels.items()]})
    comparisons = [real_dir/'view-data.json', *history]
    mutated = run(mutation_dir, '一代变异 · 8 秒搜索' + (' · 卡牌状态 v3' if frozen else ''), reference, comparisons)
    assert mutated['build_source'] == 'real_run_mutation_v1'
    assert all(b['derived'] and b['act_name'] in ('巢穴','荣耀') for b in mutated['builds'])
    labels.update({b['id']: b['label'] for b in mutated['builds']})
    assert len(set(labels.values())) == len(labels)
    assert all(labels[bid] == label for bid,label in old_labels.items())
    save(reference, {'builds':[{'id':key,'label':label} for key,label in labels.items()]})
    datasets = [mutated, real, *[read(p) for p in history]]
    fragment = (mutation_dir/'candidate.html').read_text(encoding='utf-8')
    envelope = json.loads(re.search(r'<script[^>]*id="sb-data"[^>]*>(.*?)</script>', fragment, re.S).group(1))
    payload = unpack_build_columns(unpack_strings(json.loads(gzip.decompress(base64.b64decode(envelope['data'])))))
    for dataset in payload['datasets']:
        for build in dataset['builds']: build['cards'] = [payload['card_entries'][i] for i in build['cards']]
    assert payload['datasets'] == datasets
    for folder in (real_dir, mutation_dir):
        data = json.load(gzip.open(folder/'collected-data.json.gz', 'rt', encoding='utf-8'))
        excluded = set(read(folder/'quarantined-jobs.json'))
        assert not excluded & {r['job_id'] for r in data['battles']}
    if freeze_previous:
        for source, target in zip([previous['mutation_view_data'], previous['view_data']], previous_frozen):
            assert read(target) == {**read(source), 'collection_active': False}
        retained = {'real_results_retained_in_frozen_batch': read(previous['view_data'])['stats']['battles'],
                    'mutation_results_retained_in_frozen_batch': read(previous['mutation_view_data'])['stats']['battles']}
    else:
        retained = {'real_results_preserved': preserve(previous['directory'], real_dir),
                    'mutation_results_preserved': preserve(previous['mutation_directory'], mutation_dir) if previous.get('mutation_directory') else 0}
    preserved = {**retained,
                 'frozen_8s_views': frozen,
                 'old_2s_results_unchanged':True,'lossless_payload_verified':True,'quarantines_excluded':True,
                 'batches':[d['stats']['battles'] for d in datasets]}
    save(mutation_dir/'preservation.json', preserved)
    manifest = read(real_dir/'manifest.json'); mutation_manifest = read(mutation_dir/'manifest.json')
    stamp = datetime.datetime.fromisoformat(mutation_manifest['snapshot_at_utc']).astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    updated = {**previous,'directory':str(real_dir),'view_data':str(real_dir/'view-data.json'),
        'complete':real['stats']['battles'],'builds':real['stats']['builds'],'targets':real['stats']['targets'],
        'snapshot_at_utc':manifest['snapshot_at_utc'],'job_counts':manifest['job_counts'],
        'source_export_sha256':manifest['source_export_sha256'],'previous_complete':previous['complete'],
        'mutation_directory':str(mutation_dir),'mutation_view_data':str(mutation_dir/'view-data.json'),
        'mutation_complete':mutated['stats']['battles'],'mutation_builds':mutated['stats']['builds'],
        'mutation_snapshot_at_utc':mutation_manifest['snapshot_at_utc'],
        'fragment_path':str(mutation_dir/'candidate.html'),'label_reference':str(reference),
        'display_mode':'standalone','display_dataset':'mutation' if mutated['builds'] else 'real','server_pid':None,
        'frozen_8s_views':frozen,
        'url':f'http://127.0.0.1:54260/?snapshot={stamp}','verified':False}
    save(mutation_dir/'candidate-pointer.json', updated)
    print(json.dumps({'real':real['stats']['battles'],'mutations':mutated['stats']['battles'],
                      'mutation_builds':mutated['stats']['builds'],'pointer':str(mutation_dir/'candidate-pointer.json')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--real-dir', required=True)
    parser.add_argument('--mutation-dir', required=True)
    parser.add_argument('--pointer', default='data/exports/current-view.json')
    parser.add_argument('--freeze-previous', action='store_true', help='Retain the final previous 8-second batches as separate views')
    args = parser.parse_args()
    prepare(args.real_dir, args.mutation_dir, args.pointer, args.freeze_previous)
