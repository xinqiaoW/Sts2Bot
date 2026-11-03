"""Install adaptive card-score weights while preserving existing user configuration."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil


SOURCE_FILES = ('train/reward_policy.py', 'runctl/policy.py', 'runctl/policy_config.py', 'runctl/event_policy.py')
CONFIG_FILES = ('configs/bot-policy.json', 'configs/reward-policy.json')


def install(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError('Extract the update separately from advisor-service')
    updates = {}
    for name in SOURCE_FILES:
        data = (source / name).read_bytes()
        compile(data, name, 'exec')
        updates[name] = data
    for name in CONFIG_FILES:
        current = json.loads((target / name).read_text(encoding='utf-8-sig'))
        defaults = json.loads((source / name).read_text(encoding='utf-8'))
        for key, value in defaults.items():
            current.setdefault(key, value)
        updates[name] = (json.dumps(current, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    for name in updates:
        if not (target / name).is_file():
            raise FileNotFoundError(target / name)
    backup = target / 'update-backups' / ('adaptive-weights-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    for name in updates:
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, saved)
    for name, data in updates.items():
        (target / name).write_bytes(data)
    print(f'Installed adaptive weights. Backup: {backup}. Restart the bot and advisor service.')
    return backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[1], args.target)
