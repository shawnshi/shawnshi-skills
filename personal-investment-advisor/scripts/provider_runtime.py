"""Bounded local provider calls. One retry owner; no provider data persistence.

Only owned children write IPC, and only their completed bounded file is consumed.
Provider-internal HTTP retry counts are unknown; the cap covers adapter invocations.
"""
import contextlib
import math
import multiprocessing
import os
import pickle
import re
import stat
import tempfile
import time
import traceback
from pathlib import Path

OPERATION_SECONDS = 30.0
SUPPLEMENT_SECONDS = 8.0
MAX_ATTEMPTS = 3
MAX_IPC_BYTES = 32 * 1024 * 1024
CLEANUP_SECONDS = 1.0
PERMANENT_MARKERS = (
    'invalid library', 'certificate verify failed', 'unsupported protocol',
    'invalid url', 'no host supplied', 'unable to open database file',
    'permission denied', 'access is denied', 'read-only file system',
    'yfinance_cache_unwritable',
)


def safe_diagnostic(value):
    """Bounded diagnostic prefix, not an arbitrary-secret detector.

    Discard the entire suffix after a sensitive assignment: delimiters, quotes
    and newlines cannot reliably distinguish a credential from later context.
    Never use repr (or a conversion error's text) as a fallback.
    """
    if not isinstance(value, BaseException) and type(value) not in (str, int, float):
        return '<diagnostic omitted>'
    try:
        text = str(value)[:4096]
    except Exception:
        return '<diagnostic unavailable>'
    sensitive = re.search(
        r'''(?i)(?<![a-z0-9])(?:authorization|token|password|secret|api[_-]?key)(?:\\?["'])?\s*[:=]''',
        text,
    )
    if sensitive:
        text = text[:sensitive.end()] + '<redacted>'
    text = re.sub(r'https?://\S+', '<url>', text)
    text = re.sub(r'(?i)[a-z]:[\\/][^\n\r\"\']+', '<path>', text)
    return text.replace('\r', ' ').replace('\n', ' ')[:500]


def _http_status(exc):
    """First valid HTTP status: response.status_code, status_code, then status."""
    response = getattr(exc, 'response', None)
    for source, attribute in ((response, 'status_code'), (exc, 'status_code'), (exc, 'status')):
        value = getattr(source, attribute, None)
        if isinstance(value, str) and re.fullmatch(r'[0-9]{3}', value.strip()):
            value = int(value.strip())
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return int(value)
    return None


def is_retryable_error(exc):
    """Retry only evidenced transient transport failures, never arbitrary errors."""
    return _is_retryable_error(exc, _http_status(exc))


def _is_retryable_error(exc, status):
    if isinstance(exc, (PermissionError, FileNotFoundError, TypeError, ValueError)):
        return False
    try:
        message = str(exc).lower()
    except Exception:
        return False
    if any(marker in message for marker in PERMANENT_MARKERS):
        return False
    if status is not None:
        return status in {408, 425, 429} or 500 <= status <= 599
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # requests/curl_cffi publish typed transport exceptions. Do not infer a
    # transient error from an arbitrary RuntimeError message.
    cls = type(exc)
    if cls.__module__.startswith(('requests.', 'curl_cffi.requests.')):
        return cls.__name__ in {'ConnectionError', 'Timeout', 'ConnectTimeout', 'ReadTimeout'}
    return cls.__module__.startswith('yfinance.') and cls.__name__ == 'YFRateLimitError'


def error_outcome(exc, *, phase='provider', status='error'):
    http_status = _http_status(exc)
    return {
        'status': 'timeout' if isinstance(exc, TimeoutError) else status, 'error_type': type(exc).__name__,
        'error_module': type(exc).__module__, 'error': safe_diagnostic(exc),
        'errno': getattr(exc, 'errno', None), 'phase': phase,
        'http_status': http_status,
        'provider_code': safe_diagnostic(getattr(exc, 'code', '')),
        'traceback': [
            {'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)[-12:]
        ],
        'retryable': phase == 'provider' and _is_retryable_error(exc, http_status),
    }


class ProviderError(RuntimeError):
    def __init__(self, outcome):
        self.outcome = outcome
        super().__init__(f"{outcome.get('error_type', 'ProviderError')}: {outcome.get('error', outcome['status'])}")


def require_data(outcome):
    if outcome['status'] in {'error', 'timeout'}:
        raise ProviderError(outcome)
    return outcome.get('data')


class _CappedWriter:
    def __init__(self, stream, limit):
        self.stream = stream
        self.remaining = limit

    def write(self, data):
        if len(data) > self.remaining:
            raise ValueError('provider_ipc_size_limit')
        self.remaining -= len(data)
        return self.stream.write(data)


def _child_call(function, args, kwargs, directory, limit):
    with open(os.devnull, 'w', encoding='utf-8') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        try:
            data = function(*args, **kwargs)
            empty = getattr(data, 'empty', False)
            if data is None or (isinstance(data, (dict, list, tuple)) and not data):
                empty = True
            outcome = {'status': 'no_data' if empty else 'ok', 'data': data}
        except Exception as exc:
            outcome = error_outcome(exc)
        pending = Path(directory) / 'pending'
        try:
            with pending.open('xb') as stream:
                pickle.dump(outcome, _CappedWriter(stream, limit), protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            # Serialization/storage errors are operation errors, not empty data.
            pending.unlink(missing_ok=True)
            with pending.open('xb') as stream:
                pickle.dump(error_outcome(exc, phase='ipc_write'), _CappedWriter(stream, limit))
        pending.replace(Path(directory) / 'result')


def _reap(process):
    if process.is_alive():
        process.terminate()
        process.join(timeout=CLEANUP_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(timeout=CLEANUP_SECONDS)
    if process.is_alive():
        raise RuntimeError('provider_child_cleanup_failed')
    process.close()


def _one_attempt(function, args, kwargs, deadline, limit):
    # No caller-supplied IPC path or pickle API. Temp directory is exclusively
    # parent-created; never follow symlinks or Windows reparse points.
    with tempfile.TemporaryDirectory(prefix='pia-provider-') as directory:
        context = multiprocessing.get_context('spawn')
        process = context.Process(target=_child_call, args=(function, args, kwargs, directory, limit))
        started = False
        try:
            process.start()
            started = True
            process.join(timeout=max(0.0, deadline - time.monotonic()))
            if process.is_alive():
                return error_outcome(TimeoutError('provider_operation_deadline'), phase='deadline', status='timeout')
            if process.exitcode != 0:
                return error_outcome(ChildProcessError(f'provider_child_exit:{process.exitcode}'), phase='ipc_read')
            path = Path(directory) / 'result'
            if not path.exists():
                return error_outcome(EOFError('provider_payload_missing'), phase='ipc_read')
            metadata = path.lstat()
            parent_metadata = Path(directory).lstat()
            if any(
                stat.S_ISLNK(item.st_mode) or getattr(item, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                for item in (metadata, parent_metadata)
            ) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError('provider_ipc_redirection')
            if metadata.st_size > limit:
                raise ValueError('provider_ipc_size_limit')
            with path.open('rb') as stream:
                payload = pickle.load(stream)
                if stream.read(1):
                    raise ValueError('provider_ipc_trailing_bytes')
            if not isinstance(payload, dict) or payload.get('status') not in {'ok', 'no_data', 'error', 'timeout'}:
                raise ValueError('provider_ipc_invalid_envelope')
            if payload['status'] in {'ok', 'no_data'} and 'data' not in payload:
                raise ValueError('provider_ipc_missing_data')
            if payload['status'] in {'error', 'timeout'} and not isinstance(payload.get('error_type'), str):
                raise ValueError('provider_ipc_missing_error_type')
            return payload
        except Exception as exc:
            return error_outcome(exc, phase='ipc_read' if started else 'spawn')
        finally:
            if started:
                _reap(process)
            else:
                process.close()


def run_provider(function, *args, timeout_seconds=OPERATION_SECONDS, max_attempts=MAX_ATTEMPTS, **kwargs):
    """Return ok/no_data/error/timeout with one deadline including spawn/backoff.

    Callables must be importable top-level adapter functions. No nested runtime
    invocation is allowed: it could multiply attempts and orphan descendants.
    """
    if multiprocessing.parent_process() is not None:
        return error_outcome(RuntimeError('nested_provider_runtime_forbidden'), phase='input')
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        return error_outcome(ValueError('timeout_seconds must be finite and positive'), phase='input')
    if not isinstance(max_attempts, int) or not 1 <= max_attempts <= MAX_ATTEMPTS:
        return error_outcome(ValueError('max_attempts must be 1..3'), phase='input')
    start = time.monotonic()
    deadline = start + timeout_seconds
    outcome = {}
    for attempt in range(1, max_attempts + 1):
        if time.monotonic() >= deadline:
            outcome = error_outcome(TimeoutError('provider_operation_deadline'), phase='deadline', status='timeout')
            outcome['attempts'] = attempt - 1
            break
        try:
            outcome = _one_attempt(function, args, kwargs, deadline, MAX_IPC_BYTES)
        except Exception as exc:
            outcome = error_outcome(exc, phase='cleanup_or_storage')
        outcome['attempts'] = attempt
        if not outcome.get('retryable') or attempt == max_attempts:
            break
        delay = 1.5 ** attempt
        remaining = deadline - time.monotonic()
        if remaining <= delay:
            # Last actual transport error remains visible; no redundant attempt.
            outcome['retry_budget_exhausted'] = 'deadline'
            break
        time.sleep(delay)
    outcome['elapsed_seconds'] = round(time.monotonic() - start, 6)
    outcome['timeout_seconds'] = timeout_seconds
    outcome['attempt_scope'] = 'owned_process_attempts; adapter_invocations<=attempts; provider_internal_retries_unknown'
    return outcome
