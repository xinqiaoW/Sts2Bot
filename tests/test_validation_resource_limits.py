import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator/resource_limits.py'
spec = importlib.util.spec_from_file_location('validation_resource_limits', MODULE)
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


def memory_fixture(tmp_path, limits):
    meminfo = tmp_path / 'meminfo'
    meminfo.write_text('MemTotal: 262144 kB\nMemAvailable: 131072 kB\n')
    membership = tmp_path / 'membership'
    membership.write_text('0::/user.slice/user-1014.slice/session.scope\n')
    root = tmp_path / 'cgroups'
    for relative, (limit, used) in limits.items():
        group = root / relative
        group.mkdir(parents=True, exist_ok=True)
        (group / 'memory.max').write_text(str(limit))
        (group / 'memory.current').write_text(str(used))
    return dict(meminfo=meminfo, membership=membership, cgroup_root=root)


def test_unlimited_session_still_obeys_parent_quota(tmp_path):
    inputs = memory_fixture(tmp_path, {
        'user.slice/user-1014.slice/session.scope': ('max', 10),
        'user.slice/user-1014.slice': (1000, 700),
        'user.slice': ('max', 0),
    })
    assert resources.available_memory_bytes(**inputs) == 300


def test_tightest_ancestor_and_host_both_apply(tmp_path):
    inputs = memory_fixture(tmp_path, {
        'user.slice/user-1014.slice': (1000, 400),
        'user.slice': (1000, 900),
    })
    assert resources.available_memory_bytes(**inputs) == 100
    (inputs['cgroup_root'] / 'user.slice/memory.max').write_text('max')
    (inputs['cgroup_root'] / 'user.slice/user-1014.slice/memory.max').write_text('1000000000')
    assert resources.available_memory_bytes(**inputs) == 131072 * 1024


def test_over_limit_has_no_available_memory(tmp_path):
    inputs = memory_fixture(tmp_path, {'user.slice/user-1014.slice': (100, 110)})
    assert resources.available_memory_bytes(**inputs) == 0


def test_unlimited_hierarchy_uses_host_available(tmp_path):
    inputs = memory_fixture(tmp_path, {'user.slice': ('max', 200)})
    assert resources.available_memory_bytes(**inputs) == 131072 * 1024


def test_collection_and_continuous_admission_use_account_limit(tmp_path, monkeypatch):
    from tools import collect_parallel, collect_continuous
    inputs = memory_fixture(tmp_path, {
        'user.slice/user-1014.slice/session.scope': ('max', 10),
        'user.slice/user-1014.slice': (1000, 700),
    })
    monkeypatch.setattr(collect_parallel, 'available_memory_bytes',
                        lambda: resources.available_memory_bytes(**inputs))
    assert collect_parallel.available_gib() == 300 / 1024**3
    assert collect_continuous.available_gib() == 300 / 1024**3
