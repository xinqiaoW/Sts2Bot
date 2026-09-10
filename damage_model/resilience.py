"""Preserve native failures and bound retries without changing combat labels."""
from pathlib import Path
import hashlib
import json
import re
import shutil


NATIVE_FAILURES = frozenset({
    'Failed', 'Timeout', 'ProcessExited', 'NativeStartupCacheFailure',
    'NativeEnumCacheFailure', 'NativeWinePageFault', 'NativeMenuCleanupFailure',
    'NativeFinalizerCleanupFailure', 'NativeFinalizerReuseFailure', 'NativeAssetLoadingFailure',
})


def cleanup_deadline_failure(result):
    """A native failure after combat is still a failed attempt, never a label."""
    error = result.get('error') or ''
    return (result.get('status') == 'Failed'
            and result.get('stage') == 'cleanup'
            and result.get('combatEnded') is True
            and (result.get('trainingObservation') or {}).get('complete') is True
            and 'System.TimeoutException:' in error
            and 'UnattendedTestRunner.EnsureWithinDeadline()' in error)


def native_failure_policy(config):
    policy = config.get('native_failure_policy')
    if policy is None:
        return None
    if (policy.get('name') != 'retry_then_quarantine_v1'
            or type(policy.get('max_attempts')) is not int
            or policy['max_attempts'] != 3
            or policy.get('evidence_directory') != 'evidence/native-failures-v3'):
        raise ValueError('Unsupported native failure policy')
    return policy


def preserve_failure(game, job, result, log_offset, directory):
    """Copy only this attempt's new log bytes; retain original result classification."""
    run_id = result.get('runId', '')
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('Native failure is missing its request identity')
    destination = Path(directory) / job['id'] / run_id
    destination.mkdir(parents=True, exist_ok=False)
    log_path = destination / 'native.log'
    with log_path.open('wb') as output:
        if game.log_path.exists():
            with game.log_path.open('rb') as source:
                source.seek(log_offset)
                shutil.copyfileobj(source, output)
    log_digest = hashlib.sha256()
    signatures = set()
    patterns = ('TURN_SETUP_FAILURE', 'SEARCH_FAILURE', 'field=hp', 'NATIVE_CHOICE_DRIFT',
                'MaxEnumValueCache.Get[', 'Fatal error.', 'Unhandled page fault')
    with log_path.open('rb') as source:
        for line in source:
            log_digest.update(line)
            text = line.decode('utf-8', errors='replace')
            signatures.update(pattern for pattern in patterns if pattern in text)
    record = {'job': job, 'result': result, 'diagnosis': {
        'native_status': result['status'], 'stage': result.get('stage'),
        'finished_turn': result.get('finishedTurn'), 'error': result.get('error'),
        'observed_log_signatures': sorted(signatures), 'root_cause_verified': False,
        'log_offset': log_offset, 'log_bytes': log_path.stat().st_size,
        'log_sha256': log_digest.hexdigest(), 'label_created': False}}
    manifest = destination / 'failure.json'
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    reason = f"Native status {result['status']}; stage={result.get('stage')}; signatures={sorted(signatures)}"
    return str(manifest), reason
