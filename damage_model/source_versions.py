"""Explicit source compatibility; every resulting battle still uses 0.111.0."""
from copy import deepcopy

SOURCE_SCHEMAS = {'v0.109.0': 9, 'v0.109.1': 9,
                  'v0.110.0': 10, 'v0.110.1': 10, 'v0.111.0': 10}
LEGACY_VERSIONS = tuple(v for v in SOURCE_SCHEMAS if v != 'v0.111.0')
COMPATIBILITY_REVISION = 'source_versions_109_110_v1'


def compatibility_report(run):
    version = run.get('build_id')
    return {'policy': COMPATIBILITY_REVISION, 'source_build_id': version,
            'source_schema_version': run.get('schema_version'),
            'simulation_build_id': 'v0.111.0',
            'card_aliases': {'SCARE': 'SIDESTEP'} if version in ('v0.109.0', 'v0.109.1') else {}}


def normalize_history(run):
    """Map complete card histories, not just the final deck; retain raw evidence.

    Exact model references are converted in players and floor history only.
    Upgrade, acquisition floor, enchantment and saved properties stay intact.
    The caller still checks the original version/schema and all build legality.
    """
    if run.get('build_id') not in ('v0.109.0', 'v0.109.1'):
        return run

    def convert(value):
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return 'CARD.SIDESTEP' if value == 'CARD.SCARE' else value

    normalized = deepcopy(run)
    for key in ('players', 'map_point_history'):
        if key in normalized:
            normalized[key] = convert(normalized[key])
    return normalized
