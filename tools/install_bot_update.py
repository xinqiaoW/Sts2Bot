"""Install the paired native/Python Bot update into an existing Windows bot."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil


SOURCES = ('train/reward_policy.py', 'train/scoring_horizon.py', 'train/score.py', 'train/advisor_service.py',
           'train/policy_defaults.py', 'train/live_state.py',
           'runctl/policy.py', 'runctl/policy_config.py', 'runctl/card_search.py', 'runctl/route_policy.py',
           'runctl/model_adapter.py', 'runctl/event_policy.py', 'runctl/event_combat.py', 'runctl/__main__.py', 'runctl/env.py')
CONFIGS = ('configs/bot-policy.json', 'configs/reward-policy.json')
NATIVE = ('CombatSolver.dll', 'CombatSolver.json', 'CombatSolver.MemoryCleaner.exe', 'THIRD_PARTY_NOTICES.md')


def install(source, target, bot):
    source, target, bot = Path(source).resolve(), Path(target).resolve(), Path(bot).resolve()
    if source == target:
        raise ValueError('Extract the patch separately from advisor-service')
    service_source = source / 'advisor-service' if (source / 'advisor-service').is_dir() else source
    native_source = source / 'CombatSolver' if (source / 'CombatSolver').is_dir() else source.parent / 'CombatSolver'
    if service_source == target:
        raise ValueError('Extract the patch separately from advisor-service')
    runtime = json.loads((bot / 'runtime.json').read_text(encoding='utf-8-sig'))
    if runtime.get('kind') != 'run_control':
        raise ValueError('Expected an isolated Bot runtime.json')
    mod = Path(runtime['game_dir']) / 'mods/CombatSolver'
    if not (mod / 'CombatSolver.dll').is_file():
        raise FileNotFoundError(mod / 'CombatSolver.dll')
    updates = {}
    for name in SOURCES:
        data = (service_source / name).read_bytes()
        compile(data, name, 'exec')
        dest = target / name
        if name not in ('train/scoring_horizon.py', 'runctl/event_combat.py',
                        'train/policy_defaults.py', 'train/live_state.py', 'runctl/card_search.py') and not dest.is_file():
            raise FileNotFoundError(dest)
        updates[dest] = (Path('advisor-service') / name, data)
    for name in CONFIGS:
        dest = target / name
        current = json.loads(dest.read_text(encoding='utf-8-sig'))
        defaults = json.loads((service_source / name).read_text(encoding='utf-8'))
        for key, value in defaults.items():
            current.setdefault(key, value)
        updates[dest] = (Path('advisor-service') / name, (json.dumps(current, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    manifest = json.loads((native_source / 'CombatSolver.json').read_text(encoding='utf-8'))
    if manifest.get('id') != 'CombatSolver':
        raise ValueError('Unexpected native manifest')
    for name in NATIVE:
        updates[mod / name] = (Path('CombatSolver') / name, (native_source / name).read_bytes())
    backup = target / 'update-backups' / ('bot-update-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    for dest, (relative, _) in updates.items():
        if dest.exists():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, saved)
    # Native first: a locked game DLL must not leave a newly incompatible Python installation.
    for dest in sorted(updates, key=lambda p: p.parent != mod):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(updates[dest][1])
    print(f'Installed CombatSolver {manifest["version"]} and matching policy. Mod: {mod}')
    print(f'Backup: {backup}. Restart the bot and any advisor service.')
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path, help='Installed advisor-service directory')
    parser.add_argument('--bot', required=True, type=Path, help='Bot directory containing runtime.json; close game and bot first')
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[1], args.target, args.bot)


if __name__ == '__main__':
    main()
