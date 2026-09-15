import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.lease_recovery_audit import verify_registered_reclaim


class LeaseRecoveryAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.root / 'evidence/recovery'
        self.evidence.mkdir(parents=True)
        (self.root / 'data').mkdir()
        self.row = dict(id=12, job_id='job', lease='original-lease', status='expired',
                        result='{"status":"LeaseExpired"}', finished=30)
        preflight = dict(time=20, databases={'jobs.sqlite': dict(write_lock_available=True,
                         counts={'running': 1}, expired_running=[dict(id='job', lease='original-lease',
                         status='running', lease_until=10, result=None)])},
                         runtimes={'runtime': {'lock_available': True}})
        (self.evidence / 'preflight.json').write_text(json.dumps(preflight))
        (self.evidence / 'services-started.json').write_text(json.dumps({'time': 25}))
        (self.evidence / 'worker.tail.txt').write_text(
            "self._begin_write('finish')\nsqlite3.OperationalError: database is locked\n")
        self.entry = dict(database='jobs.sqlite', attempt_id=12, job_id='job',
                          lease='original-lease', finished=30, evidence='evidence/recovery',
                          worker_logs=['worker.tail.txt'], files={})
        self.write_registry()

    def write_registry(self):
        self.entry['files'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in self.evidence.iterdir() if p.is_file()}
        (self.root / 'data/diagnosed-lease-recoveries.json').write_text(
            json.dumps({'schema': 1, 'attempts': [self.entry]}))

    def check(self):
        return verify_registered_reclaim(self.row, 'jobs.sqlite', self.root)

    def test_diagnosed_expiry_is_recognized_without_changing_evidence(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertTrue(self.check())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_unknown_attempt_or_database_is_not_waived(self):
        self.row['id'] = 13
        self.assertFalse(self.check())
        self.assertFalse(verify_registered_reclaim(self.row, 'other.sqlite', self.root))

    def test_different_lease_or_job_is_rejected(self):
        for key in ('lease', 'job_id'):
            original = self.row[key]
            self.row[key] = 'different'
            with self.assertRaises(AssertionError):
                self.check()
            self.row[key] = original

    def test_successful_native_result_cannot_be_used_as_expiry(self):
        self.row['result'] = '{"status":"Passed"}'
        with self.assertRaises(AssertionError):
            self.check()

    def test_changed_evidence_is_rejected(self):
        (self.evidence / 'worker.tail.txt').write_text('changed')
        with self.assertRaises(AssertionError):
            self.check()

    def test_live_lease_cannot_be_marked_expected(self):
        p = self.evidence / 'preflight.json'
        data = json.loads(p.read_text())
        data['databases']['jobs.sqlite']['expired_running'][0]['lease_until'] = 21
        p.write_text(json.dumps(data))
        self.write_registry()
        with self.assertRaises(AssertionError):
            self.check()

    def test_expiry_before_launch_is_rejected(self):
        self.row['finished'] = self.entry['finished'] = 24
        self.write_registry()
        with self.assertRaises(AssertionError):
            self.check()

    def test_still_owned_runtime_is_rejected(self):
        p = self.evidence / 'preflight.json'
        data = json.loads(p.read_text())
        data['runtimes']['runtime']['lock_available'] = False
        p.write_text(json.dumps(data))
        self.write_registry()
        with self.assertRaises(AssertionError):
            self.check()


if __name__ == '__main__':
    unittest.main()
