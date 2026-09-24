"""Reuse an isolated native game through its original ready/result protocol.

Each request gets a new trace file and the pinned progress snapshot is restored by
an observation mod before the original scenario starts. No combat rules change.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from damage_model.worker import GameProcess
from damage_model.provenance import sha256, verify_runtime
from run_capture import write_report
from startup_slots import StartupSlots


def wine_path(path):
    return 'Z:' + str(path).replace('/', '\\')


class StartupLimitedGameProcess(GameProcess):
    def __init__(self, **runtime):
        super().__init__(**runtime)
        self.startup_slots = StartupSlots(os.environ['STS2_NATIVE_STARTUP_LOCK_DIR'],
                                          os.environ.get('STS2_NATIVE_STARTUP_SLOTS', '8'))

    def start(self):
        self.startup_slots.acquire()
        try:
            super().start()
        except BaseException:
            self.startup_slots.release()
            raise

    def run(self, request):
        try:
            return super().run(request)
        finally:
            # Holding until the first request returns includes startup-time JIT,
            # asset loading and reflection; later requests reuse the warm process.
            self.startup_slots.release()


class PersistentCapture:
    def __init__(self, isolated, runtime_path, progress, trace_dll):
        self.isolated = Path(isolated).resolve(strict=True)
        self.runtime = json.loads(Path(runtime_path).read_text())
        for path in (self.runtime['game_dir'], self.runtime['data_dir'], self.runtime['env']['WINEPREFIX']):
            if not Path(path).resolve(strict=True).is_relative_to(self.isolated):
                raise ValueError('Native runtime escapes isolated directory')
        self.teacher = json.loads((ROOT / 'configs/teacher.json').read_text())
        verify_runtime(self.runtime, self.teacher)
        self.progress = Path(progress)
        self.trace_dll = Path(trace_dll)
        self.folder = Path(tempfile.mkdtemp(prefix='persistent-native-trace-', dir=self.isolated))
        snapshot = self.folder / 'progress-input.json'
        shutil.copyfile(self.progress, snapshot)
        snapshot.chmod(0o444)
        if sha256(snapshot) != sha256(self.progress):
            raise IOError('Progress snapshot copy changed')
        env = self.runtime.setdefault('env', {})
        env.pop('STS2_NATIVE_TRACE_PATH', None)
        env['STS2_NATIVE_TRACE_DIRECTORY'] = wine_path(self.folder)
        env['STS2_NATIVE_TRACE_PROGRESS'] = wine_path(snapshot)
        self.runtime['log_path'] = str(self.folder / 'native.log')
        self.mod = Path(self.runtime['game_dir']) / 'mods/NativeTraceProbe'
        self.mod.mkdir()
        try:
            shutil.copyfile(self.trace_dll, self.mod / 'NativeTraceProbe.dll')
            shutil.copyfile(Path(__file__).with_name('NativeTraceProbe.json'), self.mod / 'NativeTraceProbe.json')
            disk_progress = Path(self.runtime['data_dir']) / 'default/1/modded/profile1/saves/progress.save'
            disk_progress.write_bytes(snapshot.read_bytes())
            self.game = StartupLimitedGameProcess(**self.runtime)
        except BaseException:
            shutil.rmtree(self.mod)
            raise

    def capture(self, fixture, report, log):
        fixture, report, log = Path(fixture), Path(report), Path(log)
        if report.exists() or log.exists():
            raise FileExistsError('Capture evidence must not be overwritten')
        request = json.loads(fixture.read_text())['request']
        request['runId'] = uuid.uuid4().hex
        reused = self.game.process is not None and self.game.process.poll() is None
        offset = self.game.log_path.stat().st_size if self.game.log_path.exists() else 0
        started = time.monotonic()
        result = self.game.run(request)
        time.sleep(1)
        if result.get('status') != 'Passed':
            self.game.stop()
        trace = self.folder / (request['runId'] + '.jsonl')
        events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        complete = (result.get('status') == 'Passed' and result.get('combatEnded') is True
                    and bool(events) and events[0]['kind'] == 'initialized'
                    and events[0]['value'].get('runId') == request['runId']
                    and events[0]['value'].get('progressSnapshotSha256') == sha256(self.progress)
                    and not any(e['kind'] == 'trace_error' for e in events)
                    and [e['sequence'] for e in events] == list(range(1, len(events) + 1)))
        with self.game.log_path.open('rb') as stream:
            stream.seek(offset)
            with log.open('xb') as output:
                shutil.copyfileobj(stream, output)
                output.flush()
                os.fsync(output.fileno())
        capture = dict(schema='native-fixed-action-trace/v1', complete=complete,
                       productionReady=False, productionLabels=False, directory=str(self.folder),
                       request=request, result=result, events=events, wallSeconds=time.monotonic()-started,
                       teacher=self.teacher, traceModSha256=sha256(self.trace_dll),
                       captureScriptSha256=sha256(__file__), fixtureSha256=sha256(fixture),
                       progressSnapshotSha256=sha256(self.progress), reusedProcess=reused,
                       scope='Instrumented native fixed-action semantics; request-separated trace and original progress restoration; not a speed benchmark.')
        write_report(report, capture)
        return dict(exitCode=0 if complete else 1, timedOut=False, reusedProcess=reused,
                    captureImplementation=str(Path(__file__).resolve()))

    def close(self):
        self.game.stop()
        shutil.rmtree(self.mod)
