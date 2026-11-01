"""Prepare dedicated whole-run workers without touching player/collector saves."""
import argparse
import getpass
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=1)
    args = parser.parse_args()
    if args.workers < 1: parser.error('workers must be positive')
    root = Path(__file__).resolve().parents[1]
    base = args.output.resolve()
    source = root / '.runtime/game-windows'
    template = root / '.runtime/prefix-template-parallel'
    repo = root / 'vendor/CombatSolver'
    for index in range(args.workers):
        worker = base / f'worker-{index:02d}'
        # Refuse live-worker overwrite; separate preparation from deployment.
        worker.mkdir(parents=True, exist_ok=False)
        prefix, game = worker/'prefix', worker/'game'
        subprocess.run(['cp', '-a', '--reflink=auto', str(template), str(prefix)], check=True)
        game.mkdir()
        for asset in source.iterdir():
            if asset.name != 'mods': (game/asset.name).symlink_to(asset, target_is_directory=asset.is_dir())
        mods = game/'mods'; mods.mkdir()
        (mods/'STS2-RitsuLib').symlink_to(source/'mods/STS2-RitsuLib', target_is_directory=True)
        solver = mods/'CombatSolver'; solver.mkdir()
        for src in [repo/'.godot/mono/temp/bin/Release/CombatSolver.dll', repo/'CombatSolver.json', repo/'THIRD_PARTY_NOTICES.md']:
            shutil.copy2(src, solver/src.name)
        profile = prefix/'drive_c/users'/getpass.getuser()/'AppData/Roaming/SlayTheSpire2'
        profile.mkdir(parents=True, exist_ok=True)
        (profile/'combat_solver_settings.json').write_text(json.dumps({'enableNoGcRegion':False, 'searchMaxDegreeOfParallelism':1}))
        runtime = dict(kind='run_control', game_dir=str(game), data_dir=str(profile),
            command=[str(root/'.runtime/wine/root/opt/wine-stable/bin/wine'), 'SlayTheSpire2.slim.exe',
                     '--main-pack', 'SlayTheSpire2.pck', '--headless', '--disable-vsync', '--max-fps', '60', '--force-steam=off'],
            env=dict(WINEPREFIX=str(prefix), WINEDEBUG='-all', WINEDLLOVERRIDES='mshtml=',
                     COMBATSOLVER_HEADLESS='1', COMBATSOLVER_RUN_CONTROL='1', STS2_CARD_ADVISOR_DISABLED='1'),
            log_path=str(worker/'native.log'))
        path = worker/'runtime.json'; path.write_text(json.dumps(runtime, indent=2))
        print(path, flush=True)


if __name__ == '__main__': main()
