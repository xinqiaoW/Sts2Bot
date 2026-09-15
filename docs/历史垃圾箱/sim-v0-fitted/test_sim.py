"""Abstract simulator tests. Map/history tests are self-contained; environment tests
need the fitted tables (``python -m sim.tables``) and are skipped without them."""
import json
from pathlib import Path

import numpy as np
import pytest

from damage_model.catalog import Catalog

from sim.history import START_GOLD, START_HP, floor_records, is_vanilla_silent_a10
from sim.map import generate_map
from sim.tables import DEFAULT_OUTPUT, STRUCTURE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def catalog():
    return Catalog.load(ROOT / 'catalogs/game-0.111.0.raw.json', ROOT / 'configs/real-runs-8s.json')


@pytest.fixture(scope='module')
def tables():
    if not Path(DEFAULT_OUTPUT).exists():
        pytest.skip('fitted simulator tables missing; run python -m sim.tables')
    return json.loads(Path(DEFAULT_OUTPUT).read_text(encoding='utf-8'))


def synthetic_run():
    def node(kind, rooms, stats):
        return {'map_point_type': kind, 'rooms': rooms, 'player_stats': [{'player_id': 1, **stats}]}
    return {
        'schema_version': 10, 'build_id': 'v0.111.0', 'ascension': 10, 'game_mode': 'standard', 'modifiers': [],
        'players': [{'id': 1, 'character': 'CHARACTER.SILENT'}], 'win': False, 'was_abandoned': False,
        'acts': ['ACT.OVERGROWTH', 'ACT.HIVE', 'ACT.GLORY'],
        'map_point_history': [[
            node('ancient', [{'room_type': 'event', 'model_id': 'EVENT.NEOW'}],
                 {'current_hp': 56, 'max_hp': 70, 'current_gold': 99, 'hp_healed': 56,
                  'relic_choices': [{'choice': 'RELIC.POMANDER', 'was_picked': True}],
                  'ancient_choice': [{'TextKey': 'POMANDER', 'was_chosen': True}, {'TextKey': 'PRECISE_SCISSORS'}, {'TextKey': 'NEOWS_SACRIFICE'}]}),
            node('monster', [{'room_type': 'monster', 'model_id': 'ENCOUNTER.NIBBITS_WEAK'}],
                 {'current_hp': 50, 'max_hp': 70, 'current_gold': 111, 'gold_gained': 12, 'damage_taken': 6,
                  'card_choices': [{'card': {'id': 'CARD.SLICE'}, 'was_picked': True}, {'card': {'id': 'CARD.BACKFLIP'}}, {'card': {'id': 'CARD.HAZE'}}],
                  'cards_gained': [{'id': 'CARD.SLICE'}]}),
            node('elite', [{'room_type': 'elite', 'model_id': 'ENCOUNTER.BYRDONIS_ELITE'}],
                 {'current_hp': 0, 'max_hp': 70, 'current_gold': 111, 'damage_taken': 50}),
        ]],
    }


def test_floor_records_flatten_synthetic_run():
    run = synthetic_run()
    assert is_vanilla_silent_a10(run)
    records = floor_records(run, 'abc')
    assert [r['node_type'] for r in records] == ['ancient', 'monster', 'elite']
    first, fight, death = records
    assert first['hp_before'] == START_HP and first['gold_after'] == START_GOLD
    assert first['ancient_choice'] == 'POMANDER' and first['relics_gained'] == ['POMANDER'] and first['relic_count_after'] == 2
    assert fight['encounter'] == 'NIBBITS_WEAK' and fight['card_options'] == 3 and fight['card_picked'] is True
    assert fight['cards_gained'] == ['SLICE'] and fight['deck_size_after'] == 14 and fight['hp_before'] == 56 and fight['hp_after'] == 50
    assert death['final'] and death['hp_after'] == 0 and not death['win'] and not death['abandoned']
    run['acts'][0] = 'ACT.HIVE'
    assert not is_vanilla_silent_a10(run)


@pytest.mark.parametrize('act_id', ['OVERGROWTH', 'HIVE', 'GLORY'])
def test_generated_map_respects_structure(act_id):
    rng = np.random.default_rng(7)
    spec = STRUCTURE['acts'][act_id]
    for _ in range(20):
        m = generate_map(rng, spec, STRUCTURE)
        assert m.nodes[m.boss].type == 'boss' and m.nodes[m.boss].row == spec['rows'] + 1
        for n in m.nodes.values():
            if n.id == m.boss:
                continue
            assert n.children, 'every node leads somewhere'
            assert all(m.nodes[c].row == n.row + 1 for c in n.children)
            if n.row == 1:
                assert n.type == 'monster'
            if n.row == spec['treasure_row']:
                assert n.type == 'treasure'
            if n.row == spec['rows']:
                assert n.type == 'rest_site'
            if n.row < STRUCTURE['first_elite_row']:
                assert n.type not in ('elite', 'rest_site')
            if spec['rows'] - 2 <= n.row < spec['rows']:
                assert n.type != 'rest_site'
            for c in n.children:
                if n.type in ('elite', 'rest_site', 'shop') and m.nodes[c].row != spec['rows']:
                    assert m.nodes[c].type != n.type
        assert all(m.nodes[s].row == 1 for s in m.starts)


def test_env_episode_invariants(tables, catalog):
    from sim.env import PHASES, RunEnv
    from sim.oracle import EmpiricalOracle
    from sim.policies import HeuristicPolicy, RandomPolicy
    oracle = EmpiricalOracle(tables['human_damage'], seed=3)
    for seed, policy in ((1, RandomPolicy(seed=1)), (2, HeuristicPolicy(seed=2))):
        env = RunEnv(tables, catalog, oracle, seed=seed)
        steps = 0
        while not env.done:
            assert env.phase in PHASES and env.phase not in ('combat', 'done')
            actions = env.legal_actions()
            assert actions
            obs, reward, done, _info = env.step(policy.act(env))
            steps += 1
            assert 0 <= env.hp <= env.max_hp and env.gold >= 0
            assert obs['phase'] == env.phase and done == env.done
            assert steps < 2000
        assert env.history and env.history[-1]['final']
        assert env.history[-1]['win'] == env.won
        if env.won:
            assert env.act_index == 2 and env.history[-1]['node_type'] == 'boss'
        else:
            assert env.hp == 0
        # Records chain: hp_after of one floor is hp_before of the next within an act.
        for a, b in zip(env.history, env.history[1:]):
            if b['floor'] != 0:
                assert a['hp_after'] == b['hp_before']
        assert env.history[0]['node_type'] == 'ancient' and env.history[0]['relics_gained']
        build = env.build()
        catalog_ids = set(catalog.card_pool) | set(catalog.raw['character']['starting_deck'])
        assert all(c.id in catalog_ids for c in build.cards)
        assert all(r.id in catalog.relic_pool for r in build.relics)
        assert build.relics[0].id == 'RING_OF_THE_SNAKE'


def test_vec_env_batches_combat(tables, catalog):
    from sim.env import RunEnv, VecRunEnv
    from sim.oracle import CombatOracle, CombatResult
    from sim.policies import RandomPolicy

    class ZeroOracle(CombatOracle):
        name = 'zero'
        calls = 0

        def resolve(self, requests):
            self.calls += 1
            assert all(r.hp > 0 and r.target for r in requests)
            return [CombatResult(hp_loss=0, died=False) for _ in requests]

    envs = [RunEnv(tables, catalog, None, seed=100 + i) for i in range(8)]
    oracle = ZeroOracle()
    VecRunEnv(envs, oracle).run(RandomPolicy(seed=0))
    assert all(e.done and e.won for e in envs), 'no damage means every run is won'
    assert oracle.calls > 0
    fights = sum(1 for e in envs for h in e.history if h['encounter'])
    assert fights >= 8 * (3 * 3 + 1)   # at least ancient-free floors: 3 acts x >=3 fights + bosses


def test_summarize_matches_record_format(tables, catalog):
    from sim.calibrate import summarize
    from sim.env import RunEnv
    from sim.oracle import EmpiricalOracle
    from sim.policies import HeuristicPolicy
    records = []
    for seed in range(4):
        env = RunEnv(tables, catalog, EmpiricalOracle(tables['human_damage'], seed=seed), seed=seed)
        policy = HeuristicPolicy(seed=seed)
        while not env.done:
            env.step(policy.act(env))
        for r in env.history:
            r['run'] = f'sim-{seed}'
        records.extend(env.history)
    human = summarize(floor_records(synthetic_run(), 'h'), catalog)
    sim = summarize(records, catalog)
    assert human['runs'] == 1 and human['death_room']['elite'] == 1
    assert sim['runs'] == 4 and len(sim['floors_reached']) == 4
    assert sum(sim['floor_type']['OVERGROWTH'][1].values()) + sum(sim['floor_type']['UNDERDOCKS'][1].values()) == 4
