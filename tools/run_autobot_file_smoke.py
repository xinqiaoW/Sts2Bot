"""Exercise the native Windows JSON publisher with real sharing conflicts (Windows/Wine)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runctl.env import RealRunEnv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--dll', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = output / 'result.json'
    runtime = json.loads(args.runtime.read_text())
    runtime['log_path'] = str(output / 'native.log')
    runtime['env'] = {**runtime['env'], 'STS2_RUN_CONTROL_FILE_SMOKE':
        str(result) if os.name == 'nt' else 'Z:' + str(result).replace('/', '\\')}
    with RealRunEnv(runtime) as env:
        target = Path(runtime['game_dir']) / 'mods/CombatSolver'
        shutil.copy2(args.dll, target / 'CombatSolver.dll')
        shutil.copy2(ROOT / 'vendor/CombatSolver/CombatSolver.json', target / 'CombatSolver.json')
        env.game.start()
        code = env.game.process.wait(timeout=120)
        report = json.loads(result.read_text())
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if code or report['status'] != 'passed':
            raise RuntimeError('Native file sharing fixture failed; retained native.log')


if __name__ == '__main__':
    main()
