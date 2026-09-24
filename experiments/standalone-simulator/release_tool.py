#!/usr/bin/env python3
"""Build, verify, or run a frozen isolated standalone collector release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if temporary.read_bytes() != data:
        raise IOError('Manifest write verification failed')
    os.replace(temporary, path)


def verify(bundle):
    bundle = Path(bundle).resolve(strict=True)
    manifest = json.loads((bundle/'release.json').read_text())
    if manifest['schema'] != 'standalone-collector-release/v1' or manifest['productionReady'] is not False:
        raise ValueError('Expected an isolated experimental release')
    for name, expected in manifest['files'].items():
        path = (bundle/name).resolve(strict=True)
        if not path.is_relative_to(bundle) or digest(path) != expected:
            raise ValueError('Release file changed: '+name)
    for name in ('release_tool.py', 'teacher.json', 'runtime-template.json', 'host/SimulatorPrototype.dll',
                 'host/SimulatorPrototype.runtimeconfig.json', 'host/SimulatorPrototype.deps.json',
                 'progress-snapshot.json', 'damage_model/standalone.py', 'damage_model/_owned_host.py',
                 'tools/collect_continuous.py', 'tools/collect_parallel.py', 'catalogs/game-0.111.0.raw.json'):
        if name not in manifest['files']:
            raise ValueError('Required release file is not pinned: '+name)
    return manifest


def create(args):
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from damage_model.catalog import Catalog
    from damage_model.provenance import teacher_for, verify_runtime
    catalog = Catalog.load(root/'catalogs/game-0.111.0.raw.json', root/'configs/real-runs-8s.json')
    output = args.output.absolute()
    if output.exists():
        raise ValueError('Release output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name+'.'+uuid.uuid4().hex+'.staging')
    staging.mkdir()
    files = {}
    def copy(source, name):
        target = staging/name
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        with target.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if target.read_bytes() != payload:
            raise IOError('Release copy verification failed: '+name)
        files[name] = digest(target)
    try:
        for directory in ('damage_model', 'tools', 'train'):
            for path in sorted((root/directory).rglob('*.py')):
                if not path.resolve().is_relative_to(root):
                    raise ValueError('Source module escapes worktree')
                copy(path, str(path.relative_to(root)))
        for name in ('teacher.json', 'real-runs-8s.json', 'mutations-8s.json', 'mutations-targeted-8s.json'):
            copy(root/'configs'/name, 'configs/'+name)
        copy(root/'catalogs/game-0.111.0.raw.json', 'catalogs/game-0.111.0.raw.json')
        copy(Path(__file__).resolve(), 'release_tool.py')
        for suffix in ('.dll', '.runtimeconfig.json', '.deps.json'):
            copy(args.host_dll.with_suffix(suffix), 'host/SimulatorPrototype'+suffix)
        copy(args.progress_snapshot, 'progress-snapshot.json')
        teacher = dict(teacher_for(catalog, root/'configs/teacher.json'),
                       execution_backend='standalone-managed-native', validation_scope='isolated-experiment',
                       standalone_host_sha256=files['host/SimulatorPrototype.dll'],
                       standalone_unlock_state='progress-snapshot', progress_snapshot_sha256=files['progress-snapshot.json'])
        runtime = dict(backend='standalone-managed-native', game_dir=str(args.game_directory.resolve(strict=True)),
                       host_dll=str(output/'host/SimulatorPrototype.dll'), dotnet=str(args.dotnet.resolve(strict=True)),
                       progress_snapshot=str(output/'progress-snapshot.json'))
        verify_runtime({**runtime, 'host_dll':str(staging/'host/SimulatorPrototype.dll'),
                        'progress_snapshot':str(staging/'progress-snapshot.json')}, teacher)
        for name, value in (('teacher.json', teacher), ('runtime-template.json', runtime)):
            atomic_json(staging/name, value)
            files[name] = digest(staging/name)
        manifest = dict(schema='standalone-collector-release/v1', productionReady=False, productionLabels=False,
                        files=files, teacher=teacher,
                        externalDependencies=dict(gameDirectory=runtime['game_dir'], dotnet=runtime['dotnet'],
                                                  python=sys.executable, pythonVersion=sys.version),
                        scope='Frozen code and managed host for isolated acceptance. Game assemblies and Python/.NET installation remain external and require the same provisioned environment.')
        atomic_json(staging/'release.json', manifest)
        verify(staging)
        os.rename(staging, output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    print(json.dumps({'bundle':str(output), 'files':len(files), 'manifestSha256':digest(output/'release.json')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    build = commands.add_parser('create')
    for name in ('host-dll', 'game-directory', 'progress-snapshot', 'dotnet', 'output'):
        build.add_argument('--'+name, type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--bundle', type=Path, required=True)
    run = commands.add_parser('run')
    run.add_argument('--bundle', type=Path, required=True)
    run.add_argument('--module', choices=('tools.collect_parallel', 'tools.collect_continuous', 'tools.local_backup'), required=True)
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'create':
        create(args)
        return
    manifest = verify(args.bundle)
    if args.action == 'verify':
        print(json.dumps({'filesVerified':len(manifest['files']), 'productionReady':False}))
        return
    bundle = args.bundle.resolve(strict=True)
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    if args.module != 'tools.local_backup':
        indices = [i for i, value in enumerate(arguments) if value == '--teacher']
        if (len(indices) != 1 or indices[0]+1 >= len(arguments)
                or Path(arguments[indices[0]+1]).resolve() != bundle/'teacher.json'):
            raise ValueError('Release launch requires its explicit frozen teacher')
        config_indices = [i for i, value in enumerate(arguments) if value == '--config']
        if (len(config_indices) != 1 or config_indices[0]+1 >= len(arguments)
                or Path(arguments[config_indices[0]+1]).resolve() != bundle/'configs/real-runs-8s.json'):
            raise ValueError('Release launch requires its explicit frozen collection config')
        catalog = str(bundle/'catalogs/game-0.111.0.raw.json')
        if any(value == '--catalog' or value.startswith('--catalog=') for value in arguments):
            raise ValueError('Release launcher supplies its pinned catalog automatically')
        arguments = [*arguments, '--catalog', catalog]
    env = {**os.environ, 'PYTHONPATH':str(bundle), 'PYTHONSAFEPATH':'1'}
    print(json.dumps({'status':'release_verified', 'bundle':str(bundle), 'manifestSha256':digest(bundle/'release.json')}), flush=True)
    os.execve(sys.executable, [sys.executable, '-P', '-u', '-m', args.module, *arguments], env)


if __name__ == '__main__':
    main()
