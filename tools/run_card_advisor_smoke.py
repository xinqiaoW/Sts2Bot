"""Run the opt-in advisor HTTP/Godot structural fixture in an isolated Wine profile."""
import argparse
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--port', type=int, default=18766)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    work = root / '.local/card-advisor-smoke'
    work.mkdir(parents=True, exist_ok=True)
    game = work / 'game'
    source = root / '.runtime/game-windows'
    prefix = root / '.runtime/prefix-card-advisor-smoke'
    if not prefix.exists():
        subprocess.run(['cp', '-a', '--reflink=auto', str(root / '.runtime/prefix-template-parallel'), str(prefix)], check=True)
    game.mkdir(exist_ok=True)
    for asset in source.iterdir():
        target = game / asset.name
        if asset.name != 'mods' and not target.exists():
            target.symlink_to(asset, target_is_directory=asset.is_dir())
    mods = game / 'mods'
    mods.mkdir(exist_ok=True)
    if not (mods / 'STS2-RitsuLib').exists():
        (mods / 'STS2-RitsuLib').symlink_to(source / 'mods/STS2-RitsuLib', target_is_directory=True)
    destination = mods / 'CombatSolver'
    destination.mkdir(exist_ok=True)
    repo = root / 'vendor/CombatSolver'
    for src in [repo / '.godot/mono/temp/bin/Release/CombatSolver.dll', repo / 'CombatSolver.json', repo / 'THIRD_PARTY_NOTICES.md']:
        shutil.copy2(src, destination / src.name)
    fixture = args.fixture.resolve()
    result = Path(str(fixture) + '.result.json')
    # Each invocation uses a fresh result path so old evidence cannot pass.
    if result.exists():
        raise ValueError(f'Result already exists; use a new fixture filename: {result}')
    profile = prefix / 'drive_c/users/pl/AppData/Roaming/SlayTheSpire2'
    (profile / 'combat_solver_settings.json').write_text(json.dumps({'enableNoGcRegion': False, 'searchMaxDegreeOfParallelism': 1}))
    env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG='-all', WINEDLLOVERRIDES='mshtml=',
               COMBATSOLVER_HEADLESS='1', STS2_CARD_ADVISOR_URL=f'http://127.0.0.1:{args.port}/score',
               STS2_CARD_ADVISOR_SMOKE='Z:' + str(fixture).replace('/', '\\'))
    with (work / 'service.log').open('w') as service_log, (work / 'game.log').open('w') as game_log:
        service = subprocess.Popen([sys.executable, '-m', 'train.advisor_service', '--port', str(args.port)],
                                   cwd=root, stdout=service_log, stderr=subprocess.STDOUT, start_new_session=True)
        game_process = None
        try:
            deadline = time.monotonic() + 20
            while True:
                connection = http.client.HTTPConnection('127.0.0.1', args.port, timeout=1)
                try:
                    connection.request('GET', '/health')
                    if connection.getresponse().status == 200: break
                except (ConnectionRefusedError, TimeoutError):
                    if service.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Advisor service failed to start; see service.log')
                finally:
                    connection.close()
                time.sleep(0.2)
            game_process = subprocess.Popen([str(root / '.runtime/wine/root/opt/wine-stable/bin/wine'),
                'SlayTheSpire2.slim.exe', '--main-pack', 'SlayTheSpire2.pck', '--headless', '--disable-vsync',
                '--max-fps', '60', '--force-steam=off'], cwd=game, env=env,
                stdout=game_log, stderr=subprocess.STDOUT, start_new_session=True)
            code = game_process.wait(timeout=120)
            report = json.loads(result.read_text())
            print(json.dumps(dict(exit_code=code, result=str(result), **report), ensure_ascii=False, indent=2))
            if code != 0 or report['status'] != 'passed':
                raise RuntimeError('Advisor native smoke failed')
        finally:
            if game_process is not None: stop(game_process)
            stop(service)


if __name__ == '__main__':
    main()
