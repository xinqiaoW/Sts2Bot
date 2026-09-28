"""Synthetic handoff metadata; no production collection or external source calls."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_standalone_handoff import prepare_instance
from standalone_rollout_metrics import identity, read, write
from damage_model.source_backfill import historical_plan, sync_sources


@pytest.fixture
def prepared(tmp_path):
    folder = tmp_path / 'handoff'; folder.mkdir()
    bundle = tmp_path / 'bundle'; bundle.mkdir()
    write(bundle / 'release.json', {'unitFixture': True})
    write(bundle / 'runtime-template.json', dict(backend='standalone-managed-native',
          host_dll=str(bundle / 'host/SimulatorPrototype.dll'), progress_snapshot=str(bundle / 'progress-snapshot.json')))
    readiness = dict(passed=True, selectedWorkers=8, releaseManifest=identity(bundle / 'release.json'))
    cpus = sorted(os.sched_getaffinity(0))[:8]
    write(tmp_path / 'rollout/soak/launch.json', dict(cpus=cpus,
          command=['taskset', '-c', ','.join(map(str, cpus)), 'synthetic-launch'], resources={'cpuQuotaCores': 8}))
    write(tmp_path / 'rollout/soak/report.json', {'fixture': True})
    write(tmp_path / 'rollout/final-report.json', {'soak': identity(tmp_path / 'rollout/soak/report.json')})
    readiness['finalReport'] = identity(tmp_path / 'rollout/final-report.json')
    write(folder / 'readiness.json', readiness)
    original = tmp_path / 'native'; original.mkdir()
    cutoff = '2026-09-05T00:00:00Z'
    write(original / 'session.json', dict(project=str(original), state='paused',
          historical_source_start=cutoff, backfill_dir='data/external/spire-codex-history'))
    write(original / 'active.json', dict(active_db='original.sqlite'))
    native = dict(session=identity(original / 'session.json'), activePointer=identity(original / 'active.json'))
    metadata = tmp_path / 'backup'; metadata.mkdir()
    snapshot = metadata / 'real.sqlite'; snapshot.write_bytes(b'not used as a database in this metadata fixture')
    (metadata / 'collection-session.json').write_bytes((original / 'session.json').read_bytes())
    (metadata / 'active-collection.json').write_bytes((original / 'active.json').read_bytes())
    write(metadata / 'cursor.json', dict(cursor='backup-live-page', page_number=1198, next_request_at=300))
    # The live source subsequently moved ahead; only pre-snapshot positions may resume.
    write(original / 'cursor.json', dict(cursor='future-unimported-page', page_number=2000))
    write(metadata / 'source-backfill/plan.json', dict(schema=1, cutoff=cutoff,
          phases=historical_plan(cutoff), phase_index=2, state='history_complete'))
    for name in ('recent-history', 'full-archive'):
        write(metadata / 'source-backfill' / name / 'cursor.json', dict(complete=True, cursor=None))
    write(metadata / 'source-backfill/compatible-archive-v1/cursor.json',
          dict(complete=False, cursor='legacy-page', accepted_versions=['v0.109.0']))
    write(metadata / 'source-backfill/export-rate.json', dict(next_request_at=100))
    return folder, bundle, readiness, native, snapshot


def test_resume_positions_and_private_workers_preserve_native_instance(prepared, monkeypatch):
    folder, bundle, readiness, native, snapshot = prepared
    before = {key: Path(value['path']).read_bytes() for key, value in native.items()}
    result = prepare_instance(*prepared)
    assert result['productionDeployed'] is False
    assert {key: Path(value['path']).read_bytes() for key, value in native.items()} == before
    session = read(result['session']['path'])
    assert session['state'] == 'prepared' and session['controller_pid'] is None
    assert session['workers'] == 8 and session['reserve_gib'] == 16
    assert read(Path(session['source_dir']) / 'cursor.json')['cursor'] == 'backup-live-page'
    for entry in result['sources'].values():
        assert Path(entry['source']['path']).read_bytes() == Path(entry['destination']['path']).read_bytes()
    configs = [read(entry['path']) for entry in result['runtimes']]
    assert len({c['data_dir'] for c in configs}) == 8
    for config in configs:
        assert Path(config['data_dir']).is_relative_to(folder / 'instance')
        assert not list(Path(config['data_dir']).iterdir())
        assert config['env']['DOTNET_PROCESSOR_COUNT'] == '1'
        assert config['host_dll'] == str(bundle / 'host/SimulatorPrototype.dll')
    command = result['command']; assert '--catalog' not in command  # release launcher injects it
    assert command[command.index('--active-pointer') + 1] == native['activePointer']['path']
    assert read(native['activePointer']['path'])['active_db'] == 'original.sqlite'
    # Exercise the real source chooser offline: shared rate limit survives, then
    # the compatible-history cursor resumes while the live window is waiting.
    monkeypatch.setattr('damage_model.source_backfill.time.time', lambda: 50)
    assert sync_sources(None, None, None, session['source_dir'], session['source_start'],
                        session['backfill_dir'])['reason'] == 'shared_export_rate_limit'
    monkeypatch.setattr('damage_model.source_backfill.time.time', lambda: 150)
    calls = []
    def sync(*args, **kwargs):
        calls.append((args, kwargs))
        assert read(Path(args[3]) / 'cursor.json')['cursor'] == 'legacy-page'
        return {'state': 'page_imported'}
    monkeypatch.setattr('damage_model.source_backfill.sync_page', sync)
    class Catalog:
        config = {'source_compatibility_backfill': True}
    report = sync_sources(None, Catalog(), None, session['source_dir'], session['source_start'], session['backfill_dir'])
    assert report['source_stream'] == 'compatible-archive-v1' and len(calls) == 1


def test_generated_command_passes_actual_release_launcher_arguments(prepared, monkeypatch):
    result = prepare_instance(*prepared)
    spec = importlib.util.spec_from_file_location('handoff_release_test', ROOT / 'experiments/standalone-simulator/release_tool.py')
    launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
    # Release contents are a synthetic fixture; test the real CLI argument and
    # child environment logic without launching a collector or bypassing its guard.
    monkeypatch.setattr(launcher, 'verify', lambda bundle: {})
    assert result['command'][:2] == ['taskset', '-c']
    assert result['command'][2] == ','.join(map(str, result['calibration']['cpus']))
    monkeypatch.setattr(sys, 'argv', result['command'][4:])
    launched = []
    monkeypatch.setattr(launcher.os, 'execve', lambda *args: launched.append(args))
    launcher.main()
    assert len(launched) == 1
    executable, arguments, env = launched[0]
    assert arguments.count('--catalog') == 1 and 'tools.collect_continuous' in arguments
    assert env['PYTHONSAFEPATH'] == '1' and env['PYTHONPATH'] == str(prepared[1])


@pytest.mark.parametrize('change', ['unaccepted', 'workers', 'bundle', 'pointer', 'session', 'scope', 'missing_cursor', 'existing', 'cpus', 'cpu_command'])
def test_incomplete_or_changed_inputs_do_not_prepare_an_instance(prepared, change):
    folder, bundle, readiness, native, snapshot = prepared
    if change == 'unaccepted': readiness['passed'] = False
    elif change == 'workers': readiness['selectedWorkers'] = 64
    elif change == 'bundle': write(bundle / 'release.json', {'changed': True})
    elif change == 'pointer': write(native['activePointer']['path'], {'active_db': 'other.sqlite'})
    elif change == 'session': write(snapshot.parent / 'collection-session.json', {'different': True})
    elif change == 'scope':
        p = snapshot.parent / 'source-backfill/plan.json'; value = read(p); value['cutoff'] = 'different'; write(p, value)
    elif change == 'missing_cursor': (snapshot.parent / 'source-backfill/full-archive/cursor.json').unlink()
    elif change == 'existing': (folder / 'instance').mkdir(); (folder / 'instance/evidence').write_text('keep')
    elif change in ('cpus', 'cpu_command'):
        launch = Path(readiness['finalReport']['path']).parent / 'soak/launch.json'; value = read(launch)
        if change == 'cpus': value['cpus'] = [-1]
        else: value['command'] = ['unbound-search']
        write(launch, value)
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare_instance(*prepared)
    if change == 'existing': assert (folder / 'instance/evidence').read_text() == 'keep'
    else: assert not (folder / 'instance').exists()
