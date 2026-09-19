import pytest

from tools.one_off.finish_backfill_startup import EXPECTED, validate_ready


def test_ready_plan_accepts_collected_bootstrap_without_resetting_it():
    report = {'apply': True, 'sources': [{}, {}, {}],
              'jobs_added': sum(EXPECTED)-236000, 'existing_extra_seeds': 236000}
    counts = [{'pending': EXPECTED[0]-130, 'complete': 100, 'running': 25, 'quarantined': 5},
              {'pending': EXPECTED[1]}, {'pending': EXPECTED[2]}]
    validate_ready(report, counts)
    assert counts[0]['complete'] == 100 and counts[0]['running'] == 25
    counts[0]['pending'] -= 1
    counts[0]['failed'] = 1
    with pytest.raises(ValueError, match='failed'):
        validate_ready(report, counts)


def test_partial_queue_cannot_be_mistaken_for_complete_preparation():
    report = {'apply': True, 'sources': [{}, {}, {}],
              'jobs_added': sum(EXPECTED), 'existing_extra_seeds': 0}
    with pytest.raises(ValueError, match='Incomplete'):
        validate_ready(report, [{'pending': 236000}, {'pending': EXPECTED[1]}, {'pending': EXPECTED[2]}])
