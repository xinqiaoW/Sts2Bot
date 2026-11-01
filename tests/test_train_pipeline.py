"""Training pipeline tests on synthetic caches; never touch collection databases."""
import gzip
import hashlib
import json
from pathlib import Path
import random

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from damage_model.catalog import Catalog
from damage_model.encoding import Encoder
from damage_model.schema import Build, Card, Relic, canonical

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'FLYCONID_NORMAL'  # an OVERGROWTH (act 1) encounter
pytest.importorskip('scipy')
torch = pytest.importorskip('torch')

from train.features import Vocabulary, encode_pairs, sparse_features, tokens  # noqa: E402
from train.metrics import evaluate  # noqa: E402
from train.snapshot import BATTLE_SCHEMA, merge_sources  # noqa: E402


@pytest.fixture(scope='module')
def catalog():
    return Catalog.load(ROOT / 'catalogs/game-0.111.0.raw.json', ROOT / 'configs/real-runs-8s.json')


def sample_build(catalog, seed=0, act_id='OVERGROWTH'):
    rng = random.Random(seed)
    cards = [Card(c) for c in catalog.raw['character']['starting_deck']]
    pool = [c for c in catalog.card_pool if catalog.cards[c]['pool'] == 'SILENT_CARD_POOL']
    for _ in range(rng.randint(0, 6)):
        cards.append(Card(rng.choice(pool), upgrade=rng.randint(0, 1)))
    enchantment = sorted(catalog.enchantments)[0]
    cards[1] = Card(cards[1].id, 1, enchantment, rng.randint(1, 3))
    cards.append(Card('DOWSING', 0, persistent_state={'RoomsEntered': rng.randint(1, 4)}))
    neow = next(r for r in catalog.ancients['NEOW']['possible_relics'] if r in catalog.relic_pool and r != 'NEOWS_BONES' and not catalog.relics[r]['state_properties'])
    relics = [Relic('RING_OF_THE_SNAKE'), Relic(neow), Relic('PEN_NIB', (('AttacksPlayed', rng.randint(0, 9)),))]
    return Build(act_id, catalog.acts[act_id]['act'], tuple(cards), tuple(relics), ((1, 'NEOW', neow),), f'family-{seed}')


def test_sparse_features_match_dense_encoder(catalog):
    encoder = Encoder.from_catalog(catalog)
    for seed in range(5):
        build = sample_build(catalog, seed)
        target = catalog.acts[build.act_id]['encounters'][seed % 3]['id']
        dense = encoder.encode(build, target, 70)
        sparse = sparse_features(build, target, 70)
        rebuilt = np.zeros_like(dense)
        for key, value in sparse.items():
            rebuilt[encoder.positions[key]] += value
        assert np.allclose(dense, rebuilt, atol=1e-6)
        assert all(v != 0 for v in sparse.values())


def test_tokens_cover_cards_relics_target_and_global(catalog):
    build = sample_build(catalog, 1)
    toks = tokens(build, TARGET, 70)
    assert len(toks) == len(build.cards) + len(build.relics) + 2
    kinds = [t[0][0] for t in toks]
    assert kinds.count('kind:card') == len(build.cards) and kinds.count('kind:relic') == len(build.relics)
    assert any(s.startswith('state:DOWSING:') for syms, _ in toks for s in syms)
    assert any(s.startswith('counter:PEN_NIB:AttacksPlayed=') for syms, _ in toks for s in syms)


def test_vocabulary_reports_untrained_but_rejects_unknown(catalog):
    train_build = sample_build(catalog, 2)
    vocab = Vocabulary.build(catalog, [(train_build, TARGET, 70)])
    seen = sparse_features(train_build, TARGET, 70)
    assert set(seen) <= set(vocab.feature_index) and any(k.endswith(':amount_squared') for k in seen)
    other = sample_build(catalog, 3)
    idx, val, untrained = vocab.encode_sparse(other, TARGET, 70)
    assert len(idx) == len(val) and untrained  # different deck → some legal keys unseen
    bogus = Build.from_dict({**train_build.to_dict(), 'cards': [{'id': 'NOT_A_CARD', 'upgrade': 0}]})
    with pytest.raises(ValueError):
        vocab.encode_sparse(bogus, TARGET, 70)
    symbols, numerics, missing = vocab.encode_tokens(other, TARGET, 70)
    assert symbols.shape[1] == vocab.spec['token_slots'] and missing


def write_cache(directory, name, kind, builds, battles, edges, lineage=None, teacher=None):
    directory.mkdir(parents=True, exist_ok=True)
    columns = {k: [] for k in BATTLE_SCHEMA.names}
    for row in battles:
        for key in BATTLE_SCHEMA.names:
            columns[key].append(row[key])
    table = pa.table({k: pa.array(v, type=BATTLE_SCHEMA.field(k).type) for k, v in columns.items()}, schema=BATTLE_SCHEMA)
    pq.write_table(table, directory / f'{name}.battles.parquet')
    with gzip.open(directory / f'{name}.builds.json.gz', 'wt') as stream:
        json.dump({'builds': builds, 'lineage': lineage or {}}, stream)
    with gzip.open(directory / f'{name}.edges.json.gz', 'wt') as stream:
        json.dump(edges, stream)
    teacher = teacher or {'search_ms': 8000, 'solver_base': 'x', 'collector_protocol': 3}
    meta = {'name': name, 'kind': kind, 'db': f'{name}.sqlite', 'frozen': False, 'exported_at_utc': 'now', 'job_counts': {'complete': len(battles)},
            'rows': len(battles), 'builds': len(builds), 'teachers': {'t-' + name: teacher}, 'targets': {TARGET: {'id': TARGET}}}
    (directory / f'{name}.meta.json').write_text(json.dumps(meta))


def battle(build_id, seed, hp_loss, source, kind, act_id='OVERGROWTH'):
    return dict(job_id=f'{build_id}-{seed}-{source}', source=source, kind=kind, build_id=build_id, target_id=TARGET, act_id=act_id,
                seed=str(seed), teacher_id='t', run_id='r', initial_hp=70, max_hp=70, final_hp=70 - hp_loss, final_max_hp=70,
                hp_loss=hp_loss, died=hp_loss >= 70, finished_turn=3, elapsed_seconds=8.0, attempts=1, finished_at='now')


def synthetic_snapshot(tmp_path, catalog, n_builds=40):
    cache, output = tmp_path / 'sources', tmp_path / 'snapshot'
    real_builds, real_battles, edges = {}, [], []
    ids = []
    for i in range(n_builds):
        build = sample_build(catalog, i)
        real_builds[build.id] = build.to_dict(); ids.append(build.id)
        edges.append(['build:' + build.id, f'run:run-{i // 2}'])  # pairs of builds share a run
        for seed in range(4):
            real_battles.append(battle(build.id, seed, min(70, 10 + (i % 7) * 5 + seed), 'real-a', 'real'))
    write_cache(cache, 'real-a', 'real', real_builds, real_battles, edges)
    # Second real source repeats one input (duplicate) and adds a run link.
    dup = real_battles[0]
    write_cache(cache, 'real-b', 'real', {ids[0]: real_builds[ids[0]]}, [{**dup, 'source': 'real-b', 'job_id': 'dup'}],
                [['build:' + ids[0], 'run:run-0']])
    # Mutation child of build 3 keyed only by lineage.
    child = Build.from_dict({**real_builds[ids[3]], 'cards': real_builds[ids[3]]['cards'][:-1], 'family': 'child'})
    write_cache(cache, 'mut', 'mutation', {child.id: child.to_dict()}, [battle(child.id, s, 20 + s, 'mut', 'mutation') for s in range(4)],
                [['build:' + child.id, 'build:' + ids[3]]], lineage={child.id: {'parent_id': ids[3], 'size': 'small', 'axes': 'cards', 'cards_changed': 1, 'relics_changed': 0, 'sequence': 1}})
    config = {'sources': [{'name': 'real-a', 'kind': 'real', 'db': 'a'}, {'name': 'real-b', 'kind': 'real', 'db': 'b'}, {'name': 'mut', 'kind': 'mutation', 'db': 'm'}],
              'teacher_compatibility_keys': ['search_ms', 'solver_base'], 'split_buckets': {'train': 80, 'validation': 10, 'test': 10}}
    manifest = merge_sources(config, cache, output)
    return output, manifest, ids, child.id


def test_merge_dedupes_and_groups_by_run_and_lineage(tmp_path, catalog):
    output, manifest, ids, child_id = synthetic_snapshot(tmp_path, catalog)
    assert manifest['duplicates_dropped'] == {'real-b': 1}
    with gzip.open(output / 'builds.json.gz', 'rt') as stream:
        builds = {b['id']: b for b in json.load(stream)}
    assert builds[ids[0]]['group'] == builds[ids[1]]['group']            # same run
    assert builds[child_id]['group'] == builds[ids[3]]['group'] == builds[ids[2]]['group']  # lineage joins parent's run
    assert builds[child_id]['kind'] == 'mutation' and builds[child_id]['lineage']['parent_id'] == ids[3]
    assert sorted(builds[ids[0]]['sources']) == ['real-a', 'real-b']
    rows = pq.read_table(output / 'battles.parquet').to_pandas()
    assert len(rows) == manifest['rows'] == 40 * 4 + 4
    assert set(rows.groupby('group').split.nunique()) == {1}


def test_merge_rejects_incompatible_teachers(tmp_path, catalog):
    cache = tmp_path / 'sources'
    build = sample_build(catalog, 0)
    write_cache(cache, 'a', 'real', {build.id: build.to_dict()}, [battle(build.id, 0, 5, 'a', 'real')], [], teacher={'search_ms': 8000, 'solver_base': 'x'})
    write_cache(cache, 'b', 'real', {build.id: build.to_dict()}, [battle(build.id, 1, 5, 'b', 'real')], [], teacher={'search_ms': 2000, 'solver_base': 'x'})
    config = {'sources': [{'name': 'a', 'kind': 'real', 'db': 'a'}, {'name': 'b', 'kind': 'real', 'db': 'b'}],
              'teacher_compatibility_keys': ['search_ms'], 'split_buckets': {'train': 80, 'validation': 10, 'test': 10}}
    with pytest.raises(ValueError):
        merge_sources(config, cache, tmp_path / 'out')


def test_backend_mixture_is_explicit_and_still_rejects_different_search_budget(tmp_path, catalog):
    cache = tmp_path / 'sources'
    build = sample_build(catalog, 0)
    native = {'search_ms': 8000, 'solver_base': 'x'}
    simulator = {**native, 'execution_backend': 'standalone-managed-native',
                 'validation_scope': 'isolated-experiment'}
    write_cache(cache, 'native', 'real', {build.id: build.to_dict()},
                [battle(build.id, 0, 5, 'native', 'real')], [], teacher=native)
    write_cache(cache, 'simulator', 'real', {build.id: build.to_dict()},
                [battle(build.id, 1, 7, 'simulator', 'real')], [], teacher=simulator)
    config = {'sources': [{'name': n, 'kind': 'real', 'db': n} for n in ['native', 'simulator']],
              'teacher_compatibility_keys': ['search_ms', 'solver_base'],
              'split_buckets': {'train': 80, 'validation': 10, 'test': 10}}
    with pytest.raises(ValueError, match='Incompatible teacher'):
        merge_sources(config, cache, tmp_path / 'strict')
    manifest = merge_sources(config, cache, tmp_path / 'mixed', allow_backend_mixture=True)
    assert manifest['allow_backend_mixture'] and manifest['contains_experimental_results']
    assert manifest['rows'] == 2
    rows = pq.read_table(tmp_path / 'mixed/battles.parquet').to_pandas()
    assert set(rows.execution_backend) == {'native-wine', 'standalone-managed-native'}
    write_cache(cache, 'simulator', 'real', {build.id: build.to_dict()},
                [battle(build.id, 1, 7, 'simulator', 'real')], [], teacher={**simulator, 'search_ms': 2000})
    with pytest.raises(ValueError, match='8000 ms'):
        merge_sources(config, cache, tmp_path / 'wrong-budget', allow_backend_mixture=True)


def test_metrics_perfect_and_floor(tmp_path, catalog):
    import pandas as pd
    rows = pd.DataFrame([battle('b', s, 10 + s, 'a', 'real') for s in range(4)] + [battle('c', s, 30, 'a', 'real') for s in range(2)])
    rows['pair'] = rows.build_id.map({'b': 0, 'c': 1}); rows['weight'] = 1 / rows.groupby('pair').pair.transform('size'); rows['died'] = rows.died.astype(float)
    pair_mean = rows.groupby('pair').hp_loss.transform('mean').to_numpy() / 70
    metrics = evaluate(rows, pair_mean, np.zeros(len(rows)), groupers=())['overall']
    assert metrics['pair_mae_hp'] == pytest.approx(0) and metrics['death_brier'] == 0
    assert metrics['floor_within_pair_rmse_hp'] == pytest.approx(np.sqrt(np.var([10, 11, 12, 13], ddof=1) / 2))


@pytest.mark.parametrize('name', ['repo_mlp', 'tabm'])
def test_requested_neural_models_support_the_installed_runtime(catalog, name):
    from train.models import build_torch_model
    from train.train import load_model_config, loss_fn
    build = sample_build(catalog)
    vocab = Vocabulary.build(catalog, [(build, TARGET, 70)])
    hparams = load_model_config(ROOT / 'train/configs/models.json', name)
    model = build_torch_model(name, vocab, hparams)
    result = model(torch.zeros(4, vocab.n_features))
    assert result.shape == ((4, hparams['k'], 2) if name == 'tabm' else (4, 2))
    loss = loss_fn(result, torch.full((4,), 0.2), torch.zeros(4), torch.ones(4), 0.1)
    loss.backward()
    assert torch.isfinite(loss) and any(p.grad is not None for p in model.parameters())


def test_streamed_pair_features_equal_the_existing_sized_input_encoding(catalog):
    inputs = [(sample_build(catalog, i), TARGET, 70) for i in range(3)]
    vocab = Vocabulary.build(catalog, inputs)
    reference = encode_pairs(vocab, inputs)
    streamed = encode_pairs(vocab, iter(inputs), n_pairs=len(inputs))
    assert (reference['sparse'] != streamed['sparse']).nnz == 0
    for key in ['symbols', 'numerics', 'lengths']:
        assert np.array_equal(reference[key], streamed[key])
    assert reference['untrained_features'] == streamed['untrained_features']
    with pytest.raises(ValueError, match='Fewer encoding inputs'):
        encode_pairs(vocab, iter(inputs), n_pairs=len(inputs)+1)


def test_set_transformer_supports_padded_tokens_and_backward(catalog):
    from train.models import build_torch_model
    from train.train import load_model_config, loss_fn
    inputs = [(sample_build(catalog, i), TARGET, 70) for i in range(4)]
    vocab = Vocabulary.build(catalog, inputs)
    encoded = encode_pairs(vocab, inputs)
    model = build_torch_model('set_transformer', vocab,
                              load_model_config(ROOT/'train/configs/models.json', 'set_transformer'))
    output = model(torch.from_numpy(encoded['symbols']).long(), torch.from_numpy(encoded['numerics']))
    loss = loss_fn(output, torch.full((4,), .2), torch.zeros(4), torch.ones(4), .1)
    loss.backward()
    assert output.shape == (4, 2) and torch.isfinite(loss)
    assert any(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())


@pytest.mark.parametrize('ensemble', [False, True])
def test_predictions_compute_unique_inputs_and_restore_every_seed_row(ensemble):
    from types import SimpleNamespace
    from train.train import predict_rows

    class CountingModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.inputs_seen = 0

        def forward(self, inputs):
            self.inputs_seen += len(inputs)
            base = torch.stack([inputs[:, 0]*0.1, inputs[:, 0]], dim=-1)
            return torch.stack([base, base+0.2], dim=1) if ensemble else base

    pairs = torch.tensor([3, 1, 3, 3, 1, 3])
    data = SimpleNamespace(rows={'test': {'pair': pairs}}, batch=lambda p: (p.float()[:, None],))
    model = CountingModel()
    mean, death = predict_rows(model, data, 'test', batch_size=1)
    assert model.inputs_seen == 2
    assert len(mean) == len(death) == len(pairs)
    assert np.allclose(mean, pairs.numpy()*0.1+(0.1 if ensemble else 0))
    expected = torch.sigmoid(pairs.float())
    if ensemble:
        expected = (expected+torch.sigmoid(pairs.float()+0.2))/2
    assert np.allclose(death, expected.numpy())


def test_train_predict_roundtrip(tmp_path, catalog):
    from train.train import run
    from train.predict import Predictor, ensemble
    output, manifest, ids, child_id = synthetic_snapshot(tmp_path, catalog, n_builds=60)
    logs = []
    results = {}
    for model, overrides in (('repo_mlp', {'epochs': 2}), ('lightgbm', {'max_rounds': 5, 'num_threads': 2})):
        directory, metrics = run(output, model, device='cpu', output=tmp_path / 'ck' / model, overrides=overrides, catalog=catalog, log=logs.append)
        results[model] = directory
        assert (directory / 'artifact.json').exists() and (directory / 'vocab.json').exists()
        assert set(metrics) == {'train', 'validation', 'test'} and metrics['test']['overall']['rows'] > 0
    predictors = [Predictor(results['repo_mlp']), Predictor(results['lightgbm'])]
    build = sample_build(catalog, 0)
    single = predictors[0].predict(build, TARGET, 70)
    assert 0 <= single['normalized_expected_hp_loss'] <= 1 and single['expected_hp_loss'] == pytest.approx(single['normalized_expected_hp_loss'] * 70)
    combined = ensemble(predictors, [(build, TARGET, 70)])[0]
    assert combined['members'] == ['repo_mlp', 'lightgbm'] and 0 <= combined['death_probability'] <= 1
    with pytest.raises(ValueError):
        predictors[0].predict(build, 'NO_SUCH_TARGET', 70)
    artifact = json.loads((results['repo_mlp'] / 'artifact.json').read_text())
    assert artifact['snapshot']['files'] == manifest['files'] and artifact['label']['normalized'] == 'hp_loss / max_hp'
    assert artifact['code']['files']['train/train.py'] == hashlib.sha256((ROOT/'train/train.py').read_bytes()).hexdigest()
    assert 'branch' in artifact['code'] and 'commit' in artifact['code']
