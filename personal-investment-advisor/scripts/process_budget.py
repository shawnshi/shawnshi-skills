"""Owned process trees and one inherited monotonic deadline (no shell).

Windows children start suspended: assignment to a kill-on-close Job precedes
any user code. POSIX children own a session/process group. No name/PID discovery.
Nested calls reserve cleanup time so a provider stops before its route expires.
"""
import contextlib
import ctypes
import functools
import math
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Literal, overload

DEADLINE_ENV = 'PIA_DEADLINE_MONOTONIC'
CLEANUP_RESERVE_SECONDS = 2.0


def deadline_after(seconds, *, reserve=0.0):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('timeout must be finite and positive')
    deadline = time.monotonic() + seconds
    inherited = os.environ.get(DEADLINE_ENV)
    if inherited is not None:
        parent = float(inherited)
        if not math.isfinite(parent):
            raise ValueError('invalid inherited deadline')
        deadline = min(deadline, parent - reserve)
    return deadline


def remaining_seconds(seconds, *, reserve=CLEANUP_RESERVE_SECONDS):
    return max(0.0, deadline_after(seconds, reserve=reserve) - time.monotonic())


def budgeted(seconds):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            previous = os.environ.get(DEADLINE_ENV)
            os.environ[DEADLINE_ENV] = str(deadline_after(seconds))
            try:
                return function(*args, **kwargs)
            finally:
                if previous is None:
                    os.environ.pop(DEADLINE_ENV, None)
                else:
                    os.environ[DEADLINE_ENV] = previous
        return wrapped
    return decorate


class WindowsJob:
    def __init__(self):
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                        ('Flags', w.DWORD), ('Min', ctypes.c_size_t), ('Max', ctypes.c_size_t),
                        ('Count', w.DWORD), ('Affinity', ctypes.c_size_t),
                        ('Priority', w.DWORD), ('Scheduling', w.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]

        class Extended(ctypes.Structure):
            _fields_ = [('Basic', Basic), ('IO', IO), ('ProcessMemory', ctypes.c_size_t),
                        ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t),
                        ('PeakJob', ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [('UserTime', ctypes.c_int64), ('KernelTime', ctypes.c_int64),
                        ('PeriodUser', ctypes.c_int64), ('PeriodKernel', ctypes.c_int64),
                        ('Faults', w.DWORD), ('Total', w.DWORD), ('Active', w.DWORD),
                        ('Terminated', w.DWORD)]

        self.accounting = Accounting
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
            ('QueryInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            ('CloseHandle', [w.HANDLE], w.BOOL)):
            fn = getattr(self.k, name)
            fn.argtypes, fn.restype = args, result
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.k.CloseHandle(self.handle)
            raise error

    def assign_and_resume(self, process):
        handle = getattr(process, '_handle', None)
        # Popen test doubles have no native handle; production Popen always does.
        if not isinstance(handle, int):
            return
        if not self.k.AssignProcessToJobObject(self.handle, int(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        n = ctypes.WinDLL('ntdll')
        n.NtResumeProcess.argtypes = [ctypes.c_void_p]
        n.NtResumeProcess.restype = ctypes.c_long
        status = n.NtResumeProcess(int(handle))
        if status != 0:
            raise OSError(f'NtResumeProcess failed: NTSTATUS {status:#x}')

    def close(self):
        try:
            if not self.k.TerminateJobObject(self.handle, 3):
                raise ctypes.WinError(ctypes.get_last_error())
            stop = time.monotonic() + CLEANUP_RESERVE_SECONDS
            while True:
                info = self.accounting()
                if not self.k.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                if info.Active == 0:
                    break
                if time.monotonic() >= stop:
                    raise RuntimeError('owned_job_cleanup_timeout')
                time.sleep(0.005)
        finally:
            self.k.CloseHandle(self.handle)


@contextlib.contextmanager
def owned_popen(command, *, deadline, **kwargs):
    job = WindowsJob() if os.name == 'nt' else None
    process = None
    env = dict(os.environ)
    env[DEADLINE_ENV] = str(deadline)
    try:
        process = subprocess.Popen(command, env=env, shell=False,
                                   creationflags=0x4 if job else 0,
                                   start_new_session=job is None, **kwargs)
        if job:
            job.assign_and_resume(process)
        yield process
    finally:
        if job:
            job.close()
        elif process is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=CLEANUP_RESERVE_SECONDS)


class ChildOutputLimitError(RuntimeError):
    pass


def bounded_capture(command, *, timeout, cwd, limit=32 * 1024 * 1024,
                    read_bytes=64 * 1024, binary=False) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    deadline = deadline_after(timeout, reserve=CLEANUP_RESERVE_SECONDS)
    if deadline <= time.monotonic():
        raise subprocess.TimeoutExpired(command, 0)
    with owned_popen(command, deadline=deadline, cwd=str(cwd),
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0) as process:
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        streams = {name: stream for name, stream in
                   (('stdout', process.stdout), ('stderr', process.stderr)) if stream is not None}
        try:
            for stream in streams.values():
                os.set_blocking(stream.fileno(), False)
            open_streams = dict(streams)
            while True:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                exited = process.poll() is not None
                received = False
                for name, stream in list(open_streams.items()):
                    remaining = limit - len(buffers[name])
                    try:
                        data = os.read(stream.fileno(), min(read_bytes, remaining + 1))
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        data = b''
                    if not data:
                        del open_streams[name]
                        continue
                    received = True
                    if len(data) > remaining:
                        raise ChildOutputLimitError(f'{name} exceeded {limit} bytes; partial output discarded')
                    buffers[name].extend(data)
                if exited and not received:
                    break
                if not received:
                    time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
            if binary:
                return subprocess.CompletedProcess(command, process.returncode,
                                                   bytes(buffers['stdout']), bytes(buffers['stderr']))
            return subprocess.CompletedProcess(
                command, process.returncode, buffers['stdout'].decode('utf-8', errors='replace'),
                buffers['stderr'].decode('utf-8', errors='replace'))
        finally:
            for stream in streams.values():
                stream.close()


@overload
def run(command, *, timeout=300, capture_output=True, check=False,
        text: Literal[False] = False) -> subprocess.CompletedProcess[bytes]: ...


@overload
def run(command, *, timeout=300, capture_output=True, check=False,
        text: Literal[True]) -> subprocess.CompletedProcess[str]: ...


def run(command, *, timeout=300, capture_output=True, check=False, text=False) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    """Bounded capture shared by the router and nested CLI stages (no retry)."""
    reader, writer = os.pipe()
    try:
        os.set_blocking(reader, False)
    finally:
        os.close(reader)
        os.close(writer)
    result = bounded_capture(command, timeout=timeout, cwd=Path(__file__).resolve().parent,
                             binary=not text)
    if check:
        result.check_returncode()
    return result
