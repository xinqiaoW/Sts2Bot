"""Check real interprocess cold-start bounds and lock release after a crash."""
import importlib.util
import multiprocessing
from pathlib import Path
import time

import pytest

module_path = Path(__file__).resolve().parents[1] / 'experiments/native-trace-probe/startup_slots.py'
spec = importlib.util.spec_from_file_location('startup_slots', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def occupy(directory, active, peak, guard):
    slots = module.StartupSlots(directory, 2)
    slots.acquire()
    try:
        with guard:
            active.value += 1
            peak.value = max(peak.value, active.value)
        time.sleep(0.08)
        with guard:
            active.value -= 1
    finally:
        slots.release()


def hold_until_terminated(directory, ready):
    slots = module.StartupSlots(directory, 1)
    slots.acquire()
    ready.set()
    time.sleep(30)


def test_startups_are_bounded_across_processes(tmp_path):
    ctx = multiprocessing.get_context('fork')
    active, peak, guard = ctx.Value('i', 0), ctx.Value('i', 0), ctx.Lock()
    children = [ctx.Process(target=occupy, args=(tmp_path, active, peak, guard)) for _ in range(10)]
    try:
        for child in children:
            child.start()
        for child in children:
            child.join(10)
        assert all(child.exitcode == 0 for child in children)
        assert 1 <= peak.value <= 2 and active.value == 0
    finally:
        for child in children:
            if child.is_alive():
                child.kill()
                child.join()


def test_crashed_holder_releases_kernel_lock(tmp_path):
    ctx = multiprocessing.get_context('fork')
    ready = ctx.Event()
    child = ctx.Process(target=hold_until_terminated, args=(tmp_path, ready))
    child.start()
    try:
        assert ready.wait(5)
        child.kill()
        child.join(5)
        assert child.exitcode is not None
        import fcntl
        with (tmp_path / 'slot-0.lock').open('a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        if child.is_alive():
            child.kill()
            child.join()


def test_invalid_slot_limit_is_rejected(tmp_path):
    for count in (0, -1, 257):
        with pytest.raises(ValueError):
            module.StartupSlots(tmp_path, count)
