"""Keep incremental native validation contiguous even when backup checks are slow."""
import math


def native_cutoff(first_started, previous=None):
    if previous is None:
        return first_started
    # Legacy reports had only completion time; migration must recover the exact
    # validated upper bound from the corresponding preserved verification output.
    through = previous.get('native_verified_through', previous['time'])
    if not isinstance(through, (float, int)) or not math.isfinite(through):
        raise ValueError('Invalid native validation watermark')
    if through > previous['time']:
        raise ValueError('Native validation extends beyond report completion')
    return max(first_started, through - 90)


def record_native_window(report, window):
    start, end = window
    if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in window):
        raise ValueError('Invalid native validation window')
    if not start <= end <= report['time']:
        raise ValueError('Native validation window is out of order')
    report['native_verification_window'] = [start, end]
    report['native_verified_through'] = end
