"""Resource accounting and conservative gates for a frozen collector rollout."""
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def identity(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def cgroup_limits(root=Path('/sys/fs/cgroup'), membership=None):
    if membership is None:
        membership = Path('/proc/self/cgroup').read_text()
    group = next((line.split('::', 1)[1] for line in membership.splitlines() if '::' in line), None)
    if group is None:
        raise ValueError('Unified cgroup membership required for resource accounting')
    directory = root / group.lstrip('/')
    limits = []
    while directory.is_relative_to(root):
        entry = {'path': str(directory)}
        for name in ('cpu.max', 'cpu.stat', 'memory.max', 'memory.current', 'memory.events', 'memory.stat'):
            path = directory / name
            if path.exists():
                entry[name] = path.read_text().strip()
        limits.append(entry)
        if directory == root:
            break
        directory = directory.parent
    return limits


def effective_resources(limits, host_available, affinity_count):
    cpus, available = float(affinity_count), host_available
    for entry in limits:
        quota = entry.get('cpu.max', 'max 100000').split()
        if quota[0] != 'max':
            cpus = min(cpus, int(quota[0]) / int(quota[1]))
        if entry.get('memory.max', 'max') != 'max':
            stats = dict(line.split() for line in entry.get('memory.stat', '').splitlines())
            reclaimable = max(0, int(stats.get('inactive_file', 0)) - int(stats.get('file_dirty', 0)) - int(stats.get('file_writeback', 0)))
            available = min(available, max(0, int(entry['memory.max']) - int(entry['memory.current']) + reclaimable))
    return {'cpuQuotaCores': cpus, 'availableBytes': available}


def resource_snapshot():
    import psutil
    limits = cgroup_limits()
    return {'time': time.time(), 'cgroups': limits,
            **effective_resources(limits, psutil.virtual_memory().available, len(os.sched_getaffinity(0)))}


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(len(values) * fraction) - 1)] if values else None


def sampled_build(build_id):
    # Fixed before outcomes; every job for a selected build is eligible for one audit.
    return int(hashlib.sha256(('rollout-audit-v1:' + build_id).encode()).hexdigest(), 16) % 100 == 0


def search_metrics(log_paths):
    """Associate sequential host diagnostics with their exact completion run ID."""
    found = {}
    for path in log_paths:
        pending = []
        with Path(path).open(errors='replace') as stream:
            for line in stream:
                if not line.startswith('{'):
                    continue
                if '"native_detour_helper_loaded"' in line or '"blocked"' in line:
                    pending = []
                elif '"teacher_search_metrics"' in line:
                    metric = json.loads(line)
                    if not metric['reused']:
                        pending.append(metric)
                elif '"StandaloneCompleted"' in line:
                    result = json.loads(line)
                    run = result['runId']
                    if run in found:
                        raise ValueError('Duplicate host completion in diagnostics: ' + run)
                    found[run] = {'firstSearch': pending[0] if pending else None,
                                  'searchCount': len(pending),
                                  'expandedNodes': sum(x['expandedNodes'] for x in pending)}
                    pending = []
    return found


def choose_workers(reports, minimum_pairs=30):
    """Matched inputs, two orders; never equate independent search labels exactly."""
    sizes = sorted({r['workers'] for r in reports})
    if not sizes or any(sum(r['workers'] == n for r in reports) != 2 for n in sizes):
        raise ValueError('Each concurrency requires two completed opposite-order batches')
    baseline = sizes[0]
    by_size = {n: [r for r in reports if r['workers'] == n] for n in sizes}
    input_sets = [set(r['cases']) for r in reports]
    if any(s != input_sets[0] for s in input_sets):
        raise ValueError('Concurrency batches did not execute identical frozen inputs')
    base = by_size[baseline]
    valid_baseline = all(r['passed'] and r['failedAttempts'] == 0 and r['quarantined'] == 0 for r in base)
    decisions = []
    for n, group in by_size.items():
        ratios, loss_deltas, death_deltas = [], [], []
        for case in sorted(input_sets[0]):
            b = [r['cases'][case] for r in base]
            c = [r['cases'][case] for r in group]
            if not all(x['complete'] for x in b + c):
                continue
            loss_deltas.append(statistics.mean(x['netHpLoss'] for x in c) - statistics.mean(x['netHpLoss'] for x in b))
            death_deltas.append(statistics.mean(x['playerDied'] for x in c) - statistics.mean(x['playerDied'] for x in b))
            bm, cm = [x.get('firstSearch') for x in b], [x.get('firstSearch') for x in c]
            # Only budget-limited baseline searches measure lost search capacity.
            if all(x and x['boundary'] == 'TimeLimit' and x['expandedNodes'] > 0 for x in bm) and all(cm):
                ratios.append(statistics.mean(x['expandedNodes'] for x in cm) /
                              statistics.mean(x['expandedNodes'] for x in bm))
        failed = sum(r['failedAttempts'] + r['quarantined'] for r in group)
        throughput = sum(r['completed'] for r in group) * 3600 / sum(r['wallSeconds'] for r in group)
        decision = dict(workers=n, validLabelsPerHour=throughput, matchedTimedSearches=len(ratios),
                        medianExpandedRatio=statistics.median(ratios) if ratios else None,
                        meanExtraHpLoss=statistics.mean(loss_deltas) if loss_deltas else None,
                        extraDeathRate=statistics.mean(death_deltas) if death_deltas else None,
                        failedAttempts=failed)
        decision['eligible'] = (valid_baseline and all(r['passed'] for r in group) and failed == 0 and
                                len(ratios) >= minimum_pairs and decision['medianExpandedRatio'] >= .85 and
                                decision['meanExtraHpLoss'] <= 2 and decision['extraDeathRate'] <= .05)
        decisions.append(decision)
    eligible = [x for x in decisions if x['eligible']]
    if not eligible:
        return {'passed': False, 'selectedWorkers': None, 'candidates': decisions}
    best = max(x['validLabelsPerHour'] for x in eligible)
    # Prefer the smaller pool when throughput differs by no more than five percent.
    selected = min(x['workers'] for x in eligible if x['validLabelsPerHour'] >= best * .95)
    return {'passed': True, 'selectedWorkers': selected, 'candidates': decisions,
            'policy': 'Two opposite-order batches; median matched timed-search expansion >=85% of baseline, mean extra HP loss <=2, extra death rate <=5 percentage points, no failed attempts; smallest pool within 5% of best eligible throughput.'}


def combine_batches(original, supplemental):
    if len(original) != len(supplemental):
        raise ValueError('Supplement must repeat every concurrency and order')
    combined = []
    for left, right in zip(original, supplemental):
        if left['workers'] != right['workers'] or set(left['cases']) & set(right['cases']):
            raise ValueError('Supplement overlaps inputs or changes concurrency order')
        combined.append(dict(workers=left['workers'], passed=left['passed'] and right['passed'],
            completed=left['completed'] + right['completed'], wallSeconds=left['wallSeconds'] + right['wallSeconds'],
            failedAttempts=left['failedAttempts'] + right['failedAttempts'],
            quarantined=left['quarantined'] + right['quarantined'], cases={**left['cases'], **right['cases']}))
    return combined


def soak_gate(*, duration, completed, failed, quarantined, running, audit, healthy_resources, backups_verified):
    return (duration >= 86400 and completed >= 10000 and failed == 0 and running == 0 and
            quarantined / max(1, completed + quarantined) <= .01 and audit.get('passed') is True and
            healthy_resources and backups_verified)
