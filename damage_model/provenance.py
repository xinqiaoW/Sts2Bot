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
    backend = runtime.get('backend', 'native-wine')
    if backend != teacher.get('execution_backend', 'native-wine'):
        raise ValueError('Runtime backend differs from teacher')
    if backend == 'standalone-managed-native':
        if teacher.get('validation_scope') != 'isolated-experiment':
            raise ValueError('Standalone worker requires isolated experiment teacher')
        if teacher.get('standalone_host_sha256') != sha256(runtime['host_dll']):
            raise ValueError('Runtime provenance mismatch: standalone host')
        snapshot = runtime.get('progress_snapshot')
        expected_unlock = 'progress-snapshot' if snapshot else 'all'
        if teacher.get('standalone_unlock_state') != expected_unlock:
            raise ValueError('Runtime unlock state differs from teacher')
        if snapshot and teacher.get('progress_snapshot_sha256') != sha256(snapshot):
            raise ValueError('Runtime provenance mismatch: progress snapshot')
        config = json.loads(Path(runtime['host_dll']).with_suffix('.runtimeconfig.json').read_text())
        if config['runtimeOptions']['configProperties'].get('System.Runtime.TieredCompilation') is not False:
            raise ValueError('Standalone worker requires optimized JIT configuration')
        if any(key in runtime.get('env', {}) for key in ('DOTNET_TieredCompilation', 'COMPlus_TieredCompilation')):
            raise ValueError('Runtime JIT overrides are not supported')
    elif backend != 'native-wine':
        raise ValueError('Unsupported runtime backend')
    root=Path(runtime['game_dir'])
    files={'game_sha256':root/'data_sts2_windows_x86_64/sts2.dll',
           'collector_sha256':root/'mods/CombatSolver/CombatSolver.dll',
           'ritsu_sha256':root/'mods/STS2-RitsuLib/STS2-RitsuLib.dll'}
    for key,path in files.items():
        if teacher.get(key)!=sha256(path): raise ValueError(f'Runtime provenance mismatch: {key}')


def completed_by_expected_backend(job, result):
    """Bind experimental standalone completions to a separate, pinned teacher identity."""
    status = result.get('status')
    if status not in ('Passed', 'StandaloneCompleted'):
        return False
    teacher = job['teacher']
    backend = teacher.get('execution_backend', 'native-wine')
    if backend == 'native-wine':
        if status != 'Passed' or result.get('provenance', {}).get('backend', 'native-wine') != 'native-wine':
            raise ValueError('Standalone result cannot complete a native teacher job')
        return True
    if backend != 'standalone-managed-native' or status != 'StandaloneCompleted':
        raise ValueError('Result backend differs from queued teacher')
    if teacher.get('validation_scope') != 'isolated-experiment':
        raise ValueError('Standalone backend is only enabled for isolated experiments')
    source = result.get('provenance', {})
    for actual, expected in (('gameSha256', 'game_sha256'), ('solverSha256', 'collector_sha256'),
                             ('hostSha256', 'standalone_host_sha256')):
        pinned = teacher.get(expected)
        if (not isinstance(pinned, str) or len(pinned) != 64
                or any(c not in '0123456789abcdef' for c in pinned)
                or source.get(actual) != pinned):
            raise ValueError('Standalone result provenance mismatch: ' + actual)
    if (source.get('backend') != backend or source.get('collectorProtocol') != 3
            or teacher.get('collector_protocol') != 3 or source.get('testMode') is not True
            or source.get('unlockState') != teacher.get('standalone_unlock_state')
            or teacher.get('standalone_unlock_state') not in ('all', 'progress-snapshot')
            or source.get('productionValidated') is not False
            or result.get('productionReady') is not False or result.get('productionLabels') is not False):
        raise ValueError('Standalone execution scope or protocol differs from teacher')
    if teacher.get('standalone_unlock_state') == 'progress-snapshot':
        pinned = teacher.get('progress_snapshot_sha256')
        if (not isinstance(pinned, str) or len(pinned) != 64
                or any(c not in '0123456789abcdef' for c in pinned)
                or source.get('progressSnapshotSha256') != pinned):
            raise ValueError('Standalone result progress snapshot differs from teacher')
    request = result.get('collectionRequest', {})
    if (not result.get('runId') or request.get('runId') != result['runId']
            or request.get('seed') != job['seed']
            or request.get('encounterId') != job['target']['id']):
        raise ValueError('Standalone result request does not match queued job')
    return True
