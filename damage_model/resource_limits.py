"""Bound host memory availability by every cgroup v2 ancestor's allowance."""
from pathlib import Path


def available_memory_bytes(*, meminfo=Path('/proc/meminfo'),
                           membership=Path('/proc/self/cgroup'),
                           cgroup_root=Path('/sys/fs/cgroup')):
    values = dict(line.split(':', 1) for line in meminfo.read_text().splitlines())
    available = int(values['MemAvailable'].split()[0]) * 1024
    unified = next((line.split(':', 2)[2] for line in membership.read_text().splitlines()
                    if line.startswith('0::')), None)
    if unified is None:
        return available
    root = cgroup_root.resolve()
    group = root / unified.lstrip('/')
    while True:
        limit_file = group / 'memory.max'
        if limit_file.exists():
            limit = limit_file.read_text().strip()
            if limit != 'max':
                used = int((group / 'memory.current').read_text())
                available = min(available, max(0, int(limit) - used))
        if group == root:
            break
        group = group.parent
    return available
