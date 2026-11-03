"""Install the Doll Room rule without replacing the rest of the bot policy."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil


REPLACEMENTS = (
    ('from .event_policy import event_value\n',
     'from .event_policy import event_value, doll_room_options\n'),
    ('        if len(options) == 1:\n',
     "        if screen == 'EVENT' and context.get('eventId') == 'DOLL_ROOM':\n"
     '            # Apply the explicit ban before the single-option shortcut.\n'
     '            choice = self.event(state, options, context)\n'
     '        elif len(options) == 1:\n'),
    ('    def event(self, state, options, context):\n',
     '    def event(self, state, options, context):\n'
     "        if context['eventId'] == 'DOLL_ROOM':\n"
     '            options, reason = doll_room_options(options)\n'
     "            self.last_report.update(reason=reason, allowed_options=[o['index'] for o in options])\n"
     '            if len(options) == 1:\n'
     "                return options[0]['index']\n"),
)


def install(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    policy = target / 'runctl/policy.py'
    event = target / 'runctl/event_policy.py'
    content = policy.read_text(encoding='utf-8-sig')
    event.read_bytes()  # Validate both destinations before writing anything.
    for old, new in REPLACEMENTS:
        if content.count(new) == 1:
            continue
        if content.count(old) != 1:
            raise ValueError('Unrecognized policy.py; nothing installed. Send its version for a compatible patch.')
        content = content.replace(old, new, 1)
    event_content = (source / 'runctl/event_policy.py').read_bytes()
    compile(content, str(policy), 'exec')
    compile(event_content, str(event), 'exec')
    backup = target / 'update-backups' / ('doll-room-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    for path in (policy, event):
        shutil.copy2(path, backup / path.name)
    policy.write_text(content, encoding='utf-8')
    event.write_bytes(event_content)
    print(f'Installed Doll Room rule. Backup: {backup}. Restart the bot.')
    return backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[1], args.target)
