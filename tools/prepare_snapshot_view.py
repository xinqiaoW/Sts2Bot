import argparse
import base64
import re
import collections
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import zipfile
import sys
from view_payload import pack_build_columns, pack_strings

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--fragment', type=Path, required=True)
parser.add_argument('--previous', type=Path)
parser.add_argument('--comparison-view', type=Path, action='append', default=[])
parser.add_argument('--dataset-label', default='真实战前构筑')
parser.add_argument('--standalone', action='store_true',
                    help='Build for the local browser viewer; inline previews remain limited to 1 MB')
args = parser.parse_args()
OUT = args.input_dir.resolve()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from damage_model.card_state import state_description
FRAGMENT = args.fragment.resolve()
source = OUT / 'collected-data.json.gz'
source_manifest = json.loads((OUT/'source-manifest.json').read_text(encoding='utf-8'))
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_manifest['sha256']
previous = json.loads(args.previous.read_text(encoding='utf-8')) if args.previous else None
data = json.load(gzip.open(source, 'rt', encoding='utf-8'))
loc = json.loads((OUT / 'localization.json').read_text(encoding='utf-8'))
catalog = json.loads((ROOT / 'catalogs/game-0.111.0.raw.json').read_text(encoding='utf-8'))
cards = {c['id']: c for c in catalog['cards']}
acts = {a['id']: a for a in catalog['acts']}
names_missing = []

def name(group, key):
    suffix = '.name' if group == 'monsters' else '.title'
    value = loc.get(group, {}).get(key + suffix)
    # Native visual subclasses inherit the segment's localized title.
    if not value and group == 'monsters' and key in (
            'DECIMILLIPEDE_SEGMENT_FRONT', 'DECIMILLIPEDE_SEGMENT_MIDDLE', 'DECIMILLIPEDE_SEGMENT_BACK'):
        value = loc[group].get('DECIMILLIPEDE_SEGMENT.name')
    if not value:
        names_missing.append((group, key))
    return value or key

counter_names = {'TurnsSeen': '累计回合', 'AttacksPlayed': '累计攻击次数', 'TimesLifted': '举重次数',
    'GainEnergyInNextCombat': '下场获得能量', 'TimesUsed': '已使用次数', 'HasTriggered': '已触发',
    'TookDamageThisCombat': '本场已受伤', 'HasItemBeenBought': '已购物', 'SkillsPlayed':'技能牌计数',
    'TreasureRoomsEntered':'已进入宝箱房', 'CombatsSeen':'战斗计数', 'ElitesDefeated':'已击败精英',
    'IsUsed':'已使用', 'CardsAdded':'获得卡牌计数', 'CombatsLeft':'剩余战斗', 'CardsPlayed':'出牌计数',
    'CardsExhausted':'消耗牌计数', 'CombatRewardsSeen':'战斗奖励计数', 'RewardsSacrificed':'献祭奖励计数',
    'KindleCount':'添火剩余战斗', 'CombatsFinished':'已完成战斗', 'GaveRelic':'已发放遗物'}
def counters(state):
    return [f'{counter_names.get(k,k)}={"是" if v is True else "否" if v is False else v}' for k, v in state]

previous_labels = {b['id']: int(b['label'][1:]) for b in previous['builds']} if previous else {}
builds = sorted(data['builds'], key=lambda b: (0, previous_labels[b['id']]) if b['id'] in previous_labels else (1, b['generation'], b['act_id'], b['id']))
window_scoped = data.get('target_policy', {}).get('name') in ('source_floor_window_v1', 'parent_source_window_v1')
lineage = {r['build_id']: r for r in data.get('mutation_lineage', [])}
historical_targets = collections.defaultdict(set)
for battle in data['battles']:
    historical_targets[battle['build_id']].add(battle['target_id'])
selected_targets = data.get('selected_targets', {})
if window_scoped:
    assert all(b['id'] in selected_targets for b in builds)
visible_targets = {b['id']: (historical_targets[b['id']] | set(selected_targets[b['id']]))
                   if window_scoped else {t['id'] for t in acts[b['act_id']]['encounters']} for b in builds}
available_targets = {t['id']:t for b in builds for t in acts[b['act_id']]['encounters']}
available_targets = {tid: t for tid,t in available_targets.items()
                     if any(tid in tids for tids in visible_targets.values())}
targets = sorted(available_targets.values(), key=lambda t: ({'Monster':0, 'Elite':1, 'Boss':2}.get(t['room_type'],3), name('encounters', t['id'])))
bi = {b['id']: i for i, b in enumerate(builds)}
ti = {t['id']: i for i, t in enumerate(targets)}
seeds = sorted({r['seed'] for r in data['battles']})
si = {s: i for i, s in enumerate(seeds)}
assert len(seeds) <= 4
groups = collections.defaultdict(list)
for r in data['battles']:
    groups[r['build_id'], r['target_id']].append(r)
assert len({r['job_id'] for r in data['battles']}) == len(data['battles']) == data['job_counts'].get('complete',0)
assert all(r['max_hp'] == r['initial_hp'] == 70 for r in data['battles'])
assert all(len({r['seed'] for r in rows}) == len(rows) <= 4 for rows in groups.values())

view_builds = []
next_label = max(previous_labels.values(), default=0) + 1
origins = collections.defaultdict(list)
for origin in data.get('build_origins', []):
    normalization = origin.get('normalization', {})
    removed = list(dict.fromkeys(normalization.get('removed_max_hp_relics', []) +
                                 normalization.get('removed_user_relics', [])))
    origins[origin['build_id']].append({'run_hash': origin['run_hash'], 'floor': origin['floor'],
        **({'removed_relics': [name('relics', r) for r in removed]} if removed else {})})
for i, b in enumerate(builds):
    cc = collections.Counter((c['id'], c['upgrade'], c.get('enchantment_id',''), c.get('enchantment_amount',0), tuple(sorted(c.get('persistent_state', {}).items()))) for c in b['cards'])
    entries = [{'id': cid, 'name': name('cards',cid), 'upgrade':up, 'count':n,
        'enchantment': (name('enchantments', ench) + ' ' + str(amount)) if ench else '',
        **({'saved_state': state_description(cid, state)} if state_description(cid, state) else {}),
        'colorless': cards[cid]['pool']=='COLORLESS_CARD_POOL'} for (cid,up,ench,amount,state),n in sorted(cc.items())]
    label_number = previous_labels.get(b['id'])
    if label_number is None:
        label_number = next_label
        next_label += 1
    label = f'B{label_number:03d}'
    b['label'] = label
    view_builds.append({**{k:b[k] for k in ('id','split','family','generation','parent','mutation')},
        'label':label,'act_name':name('acts',b['act_id']), 'size':len(b['cards']), 'origins': origins[b['id']],
        'colorless':sum(c['count'] for c in entries if c['colorless']), 'cards':entries,
        'relics':[{'name':name('relics',r['id']),'counters':counters(r['state'])} for r in b['relics']],
        'ancient':' → '.join(f'第 {h[0]} 幕 · {h[1]} · {name("relics",h[2])}' for h in b['ancient_history']),
        'targets':[ti[t['id']] for t in acts[b['act_id']]['encounters'] if t['id'] in visible_targets[b['id']]],
        **({'active_targets': [ti[tid] for tid in selected_targets[b['id']]]} if window_scoped else {})})
    if b['id'] in lineage:
        ancestry = lineage[b['id']]
        edits = []
        for change in ancestry['changes']:
            group = 'cards' if change['kind'] == 'card' else 'relics'
            def describe(item):
                if item is None: return ''
                text = name(group, item['id'])
                if group == 'cards':
                    if item.get('upgrade'): text += '+' + (str(item['upgrade']) if item['upgrade'] > 1 else '')
                    if item.get('enchantment_id'): text += f"〔{name('enchantments', item['enchantment_id'])} {item['enchantment_amount']}〕"
                    if state_description(item['id'], item.get('persistent_state', {})):
                        text += '〔' + state_description(item['id'], item.get('persistent_state', {})) + '〕'
                elif item.get('state'): text += '（' + '；'.join(counters(item['state'])) + '）'
                return text
            operation = {'add':'添加','remove':'移除','replace':'替换','upgrade':'升级'}[change['operation']]
            before, after = describe(change['before']), describe(change['after'])
            edits.append(f'{operation}：{before} → {after}' if before and after else f'{operation}：{before or after}')
        parent_label = previous_labels.get(ancestry['parent_id'])
        view_builds[-1]['derived'] = {'parent_id':ancestry['parent_id'],
            'parent_label':f'B{parent_label:03d}' if parent_label is not None else ancestry['parent_id'][:12],
            'size':ancestry['size'],'axes':ancestry['axes'],'cards_changed':ancestry['cards_changed'],
            'relics_changed':ancestry['relics_changed'],'changes':edits}

pair_export = []
results = {}
for (bid, target), rows in groups.items():
    rows.sort(key=lambda r: r['seed'])
    losses = [r['hp_loss'] for r in rows]
    results[f'{bi[bid]}:{ti[target]}'] = [[si[r['seed']],r['hp_loss'],r['finished_turn'],int(r['died'])]
        + ([r['final_max_hp']] if r.get('final_max_hp', r['max_hp']) != r['max_hp'] else []) for r in rows]
    pair_export.append({'build_id':bid,'build_label':builds[bi[bid]]['label'], 'target_id':target,
        'target_name':name('encounters',target),'n':len(rows),'planned_seeds':4,'panel_complete':len(rows)==4,
        'in_current_scope': not window_scoped or target in selected_targets[bid],
        'mean_hp_loss':statistics.mean(losses), 'sample_std_hp_loss':statistics.stdev(losses) if len(rows)>1 else None,
        'deaths':sum(r['died'] for r in rows),'death_rate':sum(r['died'] for r in rows)/len(rows),
        'seed_losses':[{'seed':r['seed'],'hp_loss':r['hp_loss'],'died':r['died']} for r in rows]})
stats = {'battles':len(data['battles']),'builds':len(builds),'targets':len(data['targets']),'planned_targets':len(targets),'pairs':len(groups),
    'pair_sample_counts':dict(collections.Counter(len(r) for r in groups.values())),
    'distinct_card_ids':len({c['id'] for b in builds for c in b['cards']}),
    'distinct_relic_ids':len({r['id'] for b in builds for r in b['relics']}),
    'deck_size_build_counts':dict(sorted(collections.Counter(len(b['cards']) for b in builds).items())),
    'colorless_build_counts':dict(sorted(collections.Counter(b['colorless'] for b in view_builds).items())),
    'deaths':sum(r['died'] for r in data['battles']),
    'split_build_counts':dict(collections.Counter(b['split'] for b in builds)),
    'split_battle_counts':dict(collections.Counter(builds[bi[r['build_id']]]['split'] for r in data['battles']))}
stamp = datetime.datetime.fromisoformat(data['snapshot_at_utc']).astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S 北京时间')
latest = max(data['battles'], key=lambda r:r['finished_at'], default=None)
search_budgets = {t['search_ms'] for t in data['teachers'].values()}
assert len(search_budgets) == 1, 'Display each search configuration as a separate dataset'
view = {'snapshot':stamp,'dataset_label':args.dataset_label,'search_budget_ms':next(iter(search_budgets)),
    'build_source':data.get('build_source', 'spire_codex_run_v1'),
    'max_hp':70,'stats':stats,'builds':view_builds,'seeds':seeds,'planned_seed_count':4,
    'target_policy': data.get('target_policy', {'name': 'whole_act_v1'}),
    'targets':[{'id':t['id'],'name':name('encounters',t['id']), 'kind':t['room_type'],
        'monster_names':[name('monsters',m) for m in t['monsters']]} for t in targets],
    'collector_protocols':sorted({t.get('collector_protocol',1) for t in data['teachers'].values()}),
    'results':results,'default_build':bi[latest['build_id']] if latest else -1,'default_target':ti[latest['target_id']] if latest else -1}
fragment = FRAGMENT.read_text(encoding='utf-8')
fragment, replaced = re.subn(r'(<script[^>]*id="sb-data"[^>]*>).*?(</script>)', lambda m: m[1]+'__DATA__'+m[2], fragment, flags=re.S)
assert replaced == 1 and fragment.count('__DATA__') == 1
payload = {'datasets':[view,*[json.loads(path.read_text(encoding='utf-8')) for path in args.comparison_view]]}
# Intern repeated per-card display records without changing exported inventories.
# The viewer expands these references locally before rendering any dataset.
datasets = payload.get('datasets', [payload])
card_entries, card_indices, packed_datasets = [], {}, []
for dataset in datasets:
    packed_builds = []
    for build in dataset['builds']:
        indices = []
        for card in build['cards']:
            key = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if key not in card_indices:
                card_indices[key] = len(card_entries)
                card_entries.append(card)
            indices.append(card_indices[key])
        assert [card_entries[i] for i in indices] == build['cards']
        packed_builds.append({**build, 'cards':indices})
    packed_datasets.append({**dataset, 'builds':packed_builds})
payload = {'datasets':packed_datasets, 'card_entries':card_entries}
payload = pack_strings(pack_build_columns(payload))
if 'const restoreStrings = value =>' not in fragment:
    decoder = (ROOT / 'tools/view_string_decoder.js').read_text(encoding='utf-8')
    marker = '    const datasets = payload.datasets || [payload];'
    assert fragment.count(marker) == 1
    fragment = fragment.replace(marker, decoder + '\n' + marker)
# Lossless local decoding keeps every result, card and provenance record available.
encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
compressed = gzip.compress(encoded, mtime=0)
assert gzip.decompress(compressed) == encoded
payload = {'encoding': 'gzip-base64', 'data': base64.b64encode(compressed).decode('ascii')}
fragment = fragment.replace('__DATA__',json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c'))
if not args.standalone:
    assert len(fragment.encode('utf-8')) < 1_000_000, 'Use --standalone for large browser snapshots'
temporary_fragment = FRAGMENT.with_suffix('.html.tmp')
temporary_fragment.write_text(fragment,encoding='utf-8')
temporary_fragment.replace(FRAGMENT)
(OUT/'view-data.json').write_text(json.dumps(view,ensure_ascii=False),encoding='utf-8')

def save_json(filename,obj):
    (OUT/filename).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

with (OUT/'battles.jsonl').open('w',encoding='utf-8') as f:
    for r in data['battles']:
        b=builds[bi[r['build_id']]]
        record={**r,'build_label':b['label'],'split':b['split'],
            'input':{'character':'SILENT','ascension':10,'act':b['act'],'act_id':b['act_id'],
                'cards':b['cards'],'relics':b['relics'],'ancient_history':b['ancient_history']}}
        f.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
with (OUT/'pair-summaries.jsonl').open('w',encoding='utf-8') as f:
    for p in sorted(pair_export,key=lambda p:(p['build_label'],p['target_id'])):
        f.write(json.dumps(p,ensure_ascii=False,separators=(',',':'))+'\n')
save_json('builds.json',builds)
if lineage: save_json('mutation-lineage.json',list(lineage.values()))
save_json('target-scope.json', {'policy': data.get('target_policy', {'name':'whole_act_v1'}),
                              'selected_targets': selected_targets})
save_json('targets.json',[{**t,'name_zh':name('encounters',t['id']),'monsters_zh':[name('monsters',m) for m in t['monsters']]} for t in targets])
save_json('names-zh.json',{g:{k[:-len('.name' if g=='monsters' else '.title')]:v for k,v in loc[g].items() if k.endswith('.name' if g=='monsters' else '.title')} for g in ['cards','enchantments','relics','monsters','encounters','acts']})
save_json('manifest.json',{'schema_version':1,'snapshot_at_utc':data['snapshot_at_utc'],'source_db':data['source_db'],
    'source_host':data['source_host'],'collector_host_counts':data['collector_host_counts'],
    'source_export_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'job_counts':data['job_counts'],
    'teachers':data['teachers'],'statistics':stats,'dataset_kind':'validated independent battle outcomes, not model predictions',
    'target_policy':data.get('target_policy', {'name':'whole_act_v1'}),
    'excluded_from_export':'All non-complete jobs, including pending, running, failed and quarantined; retained with attempts in source database',
    'content':'Normalized combat labels and inputs. Full step-by-step play logs and native diagnostic payloads remain on server.'})
readme=f'''# 静默猎手对战数据快照

快照：{stamp}。来源：{data['source_host']} 的 `{data['source_db']}`。固定 CombatSolver 老师的原生独立对战实测结果，不是模型预测。

- 有效对战：{stats['battles']} 场；卡组与遗物配置：{len(builds)} 种；目标编组：{len(targets)} 个。
- 配置 × 目标组合：{len(groups)}；每组已完成种子数量分布：{stats['pair_sample_counts']}。
- 卡组张数分布：{stats['deck_size_build_counts']}；无色牌数量分布：{stats['colorless_build_counts']}。
- 进阶 10，满血 70/70 独立开战，无药水。死亡场次：{stats['deaths']}。
- 任务状态：{data['job_counts']}。导出只包含成功终局，运行中、待采集、失败及隔离任务和全部尝试留在源数据库。
- 当前目标规则：{data.get('target_policy', {'name':'whole_act_v1'})}。`target-scope.json` 记录当前窗口目标；历史成功继续保留，范围外未完成种子不再算待采集。页面只展示已有有效结果的构筑。
- 采集机器分布：{data['collector_host_counts']}。固定时间预算在不同机器上可能产生不同搜索结果，训练前需要检查批次差异。

`battles.jsonl` 每行一场，包含完整卡组、卡牌升级、逐张附魔类型与数值、遗物顺序与计数、怪物编组、种子、净掉血和死亡标记、采集机器。`pair-summaries.jsonl` 为同一配置/目标的种子聚合，未采满四个种子的均值是暂定值。`builds.json`、`targets.json`、`names-zh.json` 和 `manifest.json` 记录配置、中文名称与出处。

旧配置的浏览编号沿用前一版；完整 build ID 才是稳定标识。卡牌 upgrade=1 表示升级，遗物 state 保存开战计数，空数组表示没有已适配的输入计数。净掉血包含回血抵消，死亡是有效标签；超时或崩溃不产生掉血标签。
'''
(OUT/'README.md').write_text(readme,encoding='utf-8')
archive=OUT/f'silent-battles-{len(data["battles"])}-{stamp[:10].replace("-", "")}.zip'
files=['README.md','manifest.json','battles.jsonl','pair-summaries.jsonl','builds.json','targets.json','target-scope.json','names-zh.json']
if lineage: files.append('mutation-lineage.json')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for filename in files:z.write(OUT/filename,filename)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert len(z.read('battles.jsonl').splitlines())==stats['battles']
    assert len(z.read('pair-summaries.jsonl').splitlines())==stats['pairs']
print(json.dumps({'stats':stats,'fragment_bytes':FRAGMENT.stat().st_size,'zip':str(archive),'zip_bytes':archive.stat().st_size,'missing_names':sorted(set(names_missing)),
                  'default_build':builds[view['default_build']]['label'] if latest else None,
                  'default_target':name('encounters',latest['target_id']) if latest else None},ensure_ascii=False,indent=2))
