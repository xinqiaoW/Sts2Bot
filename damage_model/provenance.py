from pathlib import Path
import hashlib
import json


def sha256(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): value.update(block)
    return value.hexdigest()


def teacher_for(catalog, manifest_path):
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest['game_sha256']!=catalog.raw['game_sha256']:
        raise ValueError('Catalog and teacher use different game assemblies')
    return {**manifest,'label':'full_hp_minus_post_combat_hp_v1','character':'SILENT',
        'ascension':10,'potion_policy':'Disabled','performance_preset':'Medium',
        'search_mode':'short_only','search_ms':catalog.config['short_search_budget_ms'],
        'dop':catalog.config['search_dop'],'timeout_seconds':catalog.config['battle_timeout_seconds']}


def verify_runtime(runtime, teacher):
    root=Path(runtime['game_dir'])
    files={'game_sha256':root/'data_sts2_windows_x86_64/sts2.dll',
           'collector_sha256':root/'mods/CombatSolver/CombatSolver.dll',
           'ritsu_sha256':root/'mods/STS2-RitsuLib/STS2-RitsuLib.dll'}
    for key,path in files.items():
        if teacher.get(key)!=sha256(path): raise ValueError(f'Runtime provenance mismatch: {key}')
