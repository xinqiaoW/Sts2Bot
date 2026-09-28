"""Bind ongoing native audits to accepted code and separate production queues."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from standalone_rollout_metrics import identity, read, write
from standalone_rollout_provenance import checked_identity, require


CONTROL = ('standalone_production_audit.py', 'standalone_rollout_audit.py',
           'standalone_rollout_metrics.py', 'standalone_rollout_provenance.py',
           'run_standalone_rollout.py', 'verify_standalone_acceptance.py')


def load_context(folder):
    """Recheck immutable acceptance and mutable queue identities before auditing."""
    from run_standalone_rollout import verify_plan
    from verify_standalone_acceptance import verify_acceptance
    folder = Path(folder).resolve(strict=True)
    context = read(folder / 'plan.json')
    require(context.get('schema') == 'standalone-production-audit/v1', 'Expected production audit plan')
    for key in ('handoffPreparation', 'instancePreparation', 'readiness', 'acceptedRolloutPlan'):
        checked_identity(context[key])
    require(set(context['control']) == set(CONTROL), 'Production auditor code set differs')
    for name in CONTROL:
        require(context['control'][name] == identity(Path(__file__).parent / name), 'Production audit code changed: ' + name)
    handoff = read(context['handoffPreparation']['path'])
    require(handoff.get('prepared') is True and handoff['instance'] == context['instancePreparation']
            and handoff['readiness'] == context['readiness'], 'Handoff preparation differs')
    instance = read(context['instancePreparation']['path'])
    rollout = Path(context['acceptedRolloutPlan']['path']).parent
    readiness = verify_acceptance(rollout)
    require(readiness == read(context['readiness']['path']), 'Independent readiness evidence changed')
    native_plan = verify_plan(rollout)
    require(readiness['releaseManifest'] == handoff['releaseManifest'] == native_plan['releaseManifest'],
            'Production candidate differs from accepted candidate')
    teacher = read(Path(native_plan['bundle']) / 'teacher.json')
    require(set(context['queues']) == {'real', 'mutation', 'targeted'}, 'All three production queues required')
    paths = {name: Path(path).resolve(strict=True) for name, path in context['queues'].items()}
    require(len(set(paths.values())) == 3, 'Production queues overlap')
    for name, path in paths.items():
        require(str(path) == handoff['queues'][name]['path'], 'Production audit queue path changed')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute("SELECT value FROM collection_settings WHERE key='standalone_handoff'").fetchone()
            require(row is not None and json.loads(row[0]) == handoff['reports'][name], 'Queue lost its migration provenance')
            require(json.loads(row[0])['acceptance'] == context['readiness'], 'Queue acceptance differs')
            require(all(json.loads(r[0]) == teacher for r in db.execute('SELECT DISTINCT teacher FROM jobs')),
                    'Production queue has another teacher')
    require(Path(instance['directory']).resolve() == Path(context['instancePreparation']['path']).parent,
            'Production instance path differs')
    return native_plan, paths, teacher


def prepare(handoff_folder, rollout, directory):
    handoff_folder, rollout = Path(handoff_folder).resolve(strict=True), Path(rollout).resolve(strict=True)
    directory = Path(directory).resolve()
    require(not directory.exists(), 'Use a new production audit directory')
    handoff = read(handoff_folder / 'preparation.json')
    # These hashes apply only before collection begins. At auditor startup the
    # mutable queues are checked against their preserved migration/teacher data.
    for entry in handoff['queues'].values(): checked_identity(entry)
    checked_identity(handoff['instance']); checked_identity(handoff['readiness'])
    require(handoff.get('prepared') is True, 'Production handoff is not prepared')
    from verify_standalone_acceptance import verify_acceptance
    require(verify_acceptance(rollout) == read(handoff['readiness']['path']), 'Handoff readiness differs')
    directory.mkdir(parents=True)
    control = directory / 'control'; control.mkdir()
    for name in CONTROL: shutil.copyfile(Path(__file__).parent / name, control / name)
    plan = dict(schema='standalone-production-audit/v1',
        handoffPreparation=identity(handoff_folder / 'preparation.json'),
        instancePreparation=handoff['instance'], readiness=handoff['readiness'],
        acceptedRolloutPlan=identity(rollout / 'plan.json'),
        queues={name: entry['path'] for name, entry in handoff['queues'].items()},
        control={name: identity(control / name) for name in CONTROL})
    write(directory / 'plan.json', plan)
    command = [sys.executable, str(control / 'standalone_rollout_audit.py'), '--directory', str(directory), '--production']
    write(directory / 'preparation.json', dict(plan=identity(directory / 'plan.json'), command=command,
          productionDeployed=False, started=False,
          scope='Audit preparation only. Start under the production supervisor before starting collection; never modify accepted rollout results.'))
    return command


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('handoff', 'rollout', 'directory'): parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.handoff, args.rollout, args.directory)))
