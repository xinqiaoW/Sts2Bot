"""Owned one-request managed host; completion is validated again by Store.finish."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


class StandaloneProcess:
    def __init__(self, game_dir, data_dir, host_dll, dotnet, env=None, log_path=None, progress_snapshot=None):
        self.game_dir = Path(game_dir).resolve()
        self.data_dir = Path(data_dir).resolve()
        self.host_dll = Path(host_dll).resolve()
        self.dotnet = str(Path(dotnet).resolve())
        self.progress_snapshot = Path(progress_snapshot).resolve() if progress_snapshot else None
        self.log_path = Path(log_path or self.data_dir / 'standalone.log')
        self.env = {**os.environ, 'DOTNET_PROCESSOR_COUNT': '1', **(env or {})}
        # Ambient shell settings must not silently change the validated JIT policy.
        self.env.pop('COMPlus_TieredCompilation', None)
        self.env['DOTNET_TieredCompilation'] = '0'
        self.process = None
        self.log = None
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def stop(self):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                # SIGKILL can remain pending while the host finishes kernel I/O.
                # Allow bounded reaping time without losing ownership or turning
                # a recordable battle timeout into an unrelated worker crash.
                self.process.wait(timeout=60)
        if self.log is not None:
            self.log.close()
        self.process = self.log = None

    def run(self, request):
        self.stop()
        run_id = request['runId']
        if not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise ValueError('Invalid standalone request identity')
        if type(request['timeoutSeconds']) is not int or not 0 < request['timeoutSeconds'] <= 120:
            raise ValueError('Invalid standalone hard deadline')
        started = time.monotonic()
        source = {'backend': 'standalone-managed-native'}
        def failed(status, error):
            return {'status': status, 'runId': run_id, 'error': error, 'provenance': source,
                    'combatEnded': False, 'elapsedMilliseconds': (time.monotonic() - started) * 1000}
        folder = self.data_dir / 'standalone-requests'
        folder.mkdir(exist_ok=True)
        path = folder / (run_id + '.json')
        # Unique immutable request paths prevent reuse of stale protocol files.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(request, stream)
            stream.flush()
            os.fsync(stream.fileno())
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        offset = self.log_path.stat().st_size if self.log_path.exists() else 0
        self.log = self.log_path.open('ab')
        try:
            # Configure parent-death handling in a fresh interpreter, avoiding
            # preexec_fn's unsafe interaction with threaded callers.
            self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('_owned_host.py')),
                str(os.getpid()), self.dotnet, str(self.host_dll), str(self.game_dir),
                '--execute-request', str(path)] + ([str(self.progress_snapshot)] if self.progress_snapshot else []), cwd=self.game_dir, env=self.env,
                stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = self.process.wait(timeout=max(0.001, request['timeoutSeconds'] - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                self.stop()
                return failed('StandaloneTimeout', 'Standalone process exceeded the request hard deadline')
            self.log.flush()
            candidates = []
            diagnostic = None
            with self.log_path.open('rb') as stream:
                stream.seek(offset)
                for line in stream:
                    if not line.startswith(b'{'):
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if record.get('status') == 'StandaloneCompleted':
                        candidates.append(record)
                    elif record.get('status') == 'blocked':
                        diagnostic = record
            if code != 0:
                return failed('StandaloneFailed', (diagnostic or {}).get('error', 'Host exit code ' + str(code)))
            if len(candidates) != 1 or candidates[0].get('runId') != run_id:
                return failed('StandaloneInvalidResult', 'Expected one completion for this exact runId')
            result = candidates[0]
            if result.get('collectionRequest') != request:
                return failed('StandaloneInvalidResult', 'Host completion has a different request')
            result['elapsedMilliseconds'] = (time.monotonic() - started) * 1000
            return result
        except OSError as error:
            return failed('StandaloneFailed', str(error))
        finally:
            self.stop()
