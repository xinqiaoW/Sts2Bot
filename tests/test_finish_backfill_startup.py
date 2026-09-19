import pytest

from tools.one_off.finish_backfill_startup import require_not_stopped, validate_ready


def prepared_report(totals=(400, 200, 100)):
    return {'apply': True, 'jobs_added': sum(totals)-100, 'jobs_to_add': sum(totals)-100,
            'sources': [{'expected_output_jobs': total,
                         'existing_output_jobs': 100 if i == 0 else 0,
                         'jobs_to_add': total-(100 if i == 0 else 0)}
                        for i, total in enumerate(totals)]}


def test_ready_plan_accepts_collected_bootstrap_without_resetting_it():
    report = prepared_report()
    counts = [{'pending': 270, 'complete': 100, 'running': 25, 'quarantined': 5},
              {'pending': 200}, {'pending': 100}]
    validate_ready(report, counts)
    assert counts[0]['complete'] == 100 and counts[0]['running'] == 25
    counts[0]['pending'] -= 1
    counts[0]['failed'] = 1
    with pytest.raises(ValueError, match='failed'):
        validate_ready(report, counts)


def test_partial_queue_cannot_be_mistaken_for_complete_preparation():
    with pytest.raises(ValueError, match='Incomplete'):
        validate_ready(prepared_report(), [{'pending': 300}, {'pending': 200}, {'pending': 100}])


def test_inconsistent_report_is_rejected():
    report = prepared_report()
    report['sources'][0]['expected_output_jobs'] += 20
    with pytest.raises(ValueError, match='reconcile'):
        validate_ready(report, [{'pending': 420}, {'pending': 200}, {'pending': 100}])


@pytest.mark.parametrize('marker', ['pipeline.stop', 'resource-guard-stop.json'])
def test_stop_marker_blocks_startup_and_transition(tmp_path, marker):
    require_not_stopped(tmp_path)
    (tmp_path/marker).write_text('stopped')
    with pytest.raises(RuntimeError, match='do not resume'):
        require_not_stopped(tmp_path)
