"""Install the Python card-search update, preserving unrelated user settings."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil


SOURCE_FILES = ('train/reward_policy.py', 'runctl/policy.py', 'runctl/policy_config.py')
TAIL_KEYS = ('leaf_top_fraction', 'leaf_bottom_fraction', 'leaf_top_weight', 'leaf_bottom_weight')
CONFIG_KEYS = dict.fromkeys(('configs/bot-policy.json', 'configs/reward-policy.json'), TAIL_KEYS)
COMPAT_KEYS = {
    'configs/bot-policy.json': ('samples_per_parent', 'keep_per_parent', 'lookahead_pairs',
                              'crisis_samples_per_parent', 'crisis_keep_per_parent', 'leaf_rank_power'),
    'configs/reward-policy.json': ('samples_per_parent', 'keep_per_parent', 'lookahead_pairs'),
}


def install(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError('Extract the update separately from the installed advisor-service')
    # Read and validate all inputs before modifying the installation.
    updates = {}
    for name in SOURCE_FILES:
        data = (source / name).read_bytes()
        compile(data, name, 'exec')
        updates[name] = data
    for name, keys in CONFIG_KEYS.items():
        current = json.loads((target / name).read_text(encoding='utf-8-sig'))
        defaults = json.loads((source / name).read_text(encoding='utf-8'))
        current.update({key: defaults[key] for key in keys})
        for key in COMPAT_KEYS[name]:
            current.setdefault(key, defaults[key])
        updates[name] = (json.dumps(current, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    for name in updates:
        if not (target / name).is_file():
            raise FileNotFoundError(target / name)
    backup = target / 'update-backups' / ('card-search-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    for name in updates:
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, saved)
    print(f'Backup: {backup}', flush=True)
    for name, data in updates.items():
        (target / name).write_bytes(data)
    print('Installed. Restart the bot and any running advisor service.', flush=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True, help='Installed advisor-service folder; stop it first')
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[1], args.target)


if __name__ == '__main__':
    main()
