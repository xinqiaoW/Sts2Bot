import json
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip('fcntl')
from tools import rental_backup


class EndLoop(BaseException):
    pass


def arrange(monkeypatch, tmp_path, argv, now, counts):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    monkeypatch.setattr(sys, 'argv', ['rental_backup', *argv])
    uploads, sleeps = [], []

    def upload(args):
        uploads.append(args)
        rental_backup.atomic_json('data/rental-backup.json', {'state': 'uploaded'})
        return {'counts': counts}

    def sleep(seconds):
        sleeps.append(seconds)
        raise EndLoop()

    monkeypatch.setattr(rental_backup, 'upload', upload)
    monkeypatch.setattr(rental_backup, 'time', SimpleNamespace(time=lambda: now, sleep=sleep))
    return uploads, sleeps


def test_no_deadline_continues_even_when_collection_is_idle(monkeypatch, tmp_path):
    uploads, sleeps = arrange(monkeypatch, tmp_path, [], 1788689000, {'complete': 42})
    with pytest.raises(EndLoop):
        rental_backup.main()
    assert len(uploads) == 1 and uploads[0].stop_at is None
    assert sleeps == [300]
    assert 'final' not in json.loads((tmp_path / 'data/rental-backup.json').read_text())


def test_explicit_deadline_still_finalizes_after_jobs_drain(monkeypatch, tmp_path):
    uploads, sleeps = arrange(monkeypatch, tmp_path, ['--stop-at', '1000'], 1001, {'complete': 42})
    rental_backup.main()
    assert len(uploads) == 1 and sleeps == []
    assert json.loads((tmp_path / 'data/rental-backup.json').read_text())['final'] is True


def test_explicit_deadline_waits_for_running_jobs(monkeypatch, tmp_path):
    uploads, sleeps = arrange(monkeypatch, tmp_path, ['--stop-at', '1000'], 1001, {'running': 1})
    with pytest.raises(EndLoop):
        rental_backup.main()
    assert len(uploads) == 1 and sleeps == [15]
    assert 'final' not in json.loads((tmp_path / 'data/rental-backup.json').read_text())


def test_once_can_back_up_without_a_deadline(monkeypatch, tmp_path):
    uploads, sleeps = arrange(monkeypatch, tmp_path, ['--once'], 1788689000, {'complete': 42})
    rental_backup.main()
    assert len(uploads) == 1 and sleeps == []
