"""Native bot settings/grid checks in an explicitly isolated existing runtime."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runctl.env import RealRunEnv, atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--dll', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ui-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runtime = json.loads(args.runtime.read_text())
    runtime['log_path'] = str(output / 'native.log')
    settings_path = Path(runtime['data_dir']) / 'combat_solver_settings.json'
    original = settings_path.read_bytes() if settings_path.exists() else None
    try:
        with RealRunEnv(runtime) as env:
            # Ownership is acquired before changing this dedicated runtime.
            target = Path(runtime['game_dir']) / 'mods/CombatSolver'
            shutil.copy2(args.dll, target / 'CombatSolver.dll')
            shutil.copy2(ROOT / 'vendor/CombatSolver/CombatSolver.json', target / 'CombatSolver.json')
            atomic_json(settings_path, dict(performanceMigrationVersion=243, performancePreset='Custom',
                shortTimeLimitSeconds=3, deepTimeLimitSeconds=7, searchMaxDegreeOfParallelism=2,
                enableNoGcRegion=False))
            if not args.ui_only:
                env.combat_search_mode = 'settings'
                env.combat_timeout_seconds = 1800
                observation = env.reset('SEARCHSETTINGSSMOKE', decision_mode='all', timeout_seconds=120)
                events = [json.loads(line) for line in (env.run_dir / 'events.jsonl').read_text().splitlines()]
                details = next(e['payload']['details'] for e in events if e['kind'] == 'run_started')
                assert details['combatSearchMode'] == 'settings' and details['forceShortOnly'] is False
                assert (details['shortBudgetMs'], details['deepBudgetMs'], details['searchDop']) == (3000, 7000, 2)
                atomic_json(output / 'settings-result.json', dict(status='passed', details=details,
                    run_id=env.run_id, first_screen=observation['screen'], intentionally_stopped=True))
                print('PLAYER_SEARCH_SETTINGS_PASSED', flush=True)
        result = output / 'grid-result.json'
        runtime['env'] = {**runtime['env'], 'STS2_RUN_CONTROL_UI_SMOKE': 'Z:' + str(result).replace('/', '\\')}
        with RealRunEnv(runtime) as env:
            env.game.start()
            code = env.game.process.wait(timeout=120)
            report = json.loads(result.read_text())
            print(json.dumps(report, ensure_ascii=False), flush=True)
            if code or report['status'] != 'passed':
                raise RuntimeError('Native grid fixture failed; retained native.log')
    finally:
        if original is None:
            settings_path.unlink(missing_ok=True)
        else:
            settings_path.write_bytes(original)


if __name__ == '__main__':
    main()
