"""Fixed WSL IP-network-namespace launcher; filesystem and AF_UNIX are not isolated."""
import argparse
import errno
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile

LIMIT = 8 * 1024 * 1024
GUEST_SECONDS = 45


class CapabilityError(ValueError):
    pass


def linux_path(value):
    text = str(value)
    if text.startswith(('\\\\','//')) or re.fullmatch(r'[A-Za-z]:[\\/][A-Za-z0-9_ .\\/:-]+', text) is None:
        raise ValueError('only local absolute drive paths with safe path characters accepted')
    drive = text[0].lower()
    if drive != 'c' or any(part in ('.','..','') for part in re.split(r'[\\/]', text[3:])) or ':' in text[2:]:
        raise ValueError('unsafe or unsupported drive/path')
    return '/mnt/' + drive + '/' + text[3:].replace('\\','/')


def captured(command, timeout, *, guest=False):
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(command, stdout=out, stderr=err, env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'} if guest else None,
                                   start_new_session=guest)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if guest:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)
            raise CapabilityError('isolated child lifecycle deadline exceeded; no host fallback')
        if out.tell() > LIMIT or err.tell() > LIMIT:
            raise ValueError('isolated output size limit')
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(LIMIT+1), err.read(LIMIT+1)
        if len(stdout) > LIMIT or len(stderr) > LIMIT:
            raise ValueError('isolated output size limit')
        # WSL environment warnings can contain host proxy metadata; never echo stderr.
        if not stdout:
            raise CapabilityError(f'isolated process failed: exit={code}, stderr_bytes={len(stderr)}; no host fallback')
        result = json.loads(stdout.decode('utf-8'))
        if code != {'complete':0,'incomplete':1,'insufficient_evidence':2,'failed':3}.get(result.get('status')):
            raise ValueError(f'isolated exit/status mismatch: exit={code}')
        if guest and result.get('isolation_proof'):
            child_pid = result['isolation_proof']['guest_pid']
            if Path(f'/proc/{child_pid}').exists() or Path(f'/proc/{process.pid}').exists():
                raise CapabilityError('owned guest process not reaped')
            result['isolation_lifecycle'] = {'owned_timeout_pid':process.pid, 'guest_pid':child_pid,
                                           'wait_completed':True, 'owned_pids_absent':True,
                                           'guest_timeout_seconds':GUEST_SECONDS}
        return result


def proof(parent):
    current = os.readlink('/proc/self/ns/net')
    if current == parent or not re.fullmatch(r'net:\[[0-9]+\]', parent):
        raise CapabilityError('network namespace isolation not established')
    outcomes = []
    for family, address in ((socket.AF_INET, ('1.1.1.1',443)), (socket.AF_INET6, ('2606:4700:4700::1111',443))):
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(1)
            try:
                connection.connect(address)
            except OSError as exc:
                if exc.errno not in (errno.ENETUNREACH, errno.EADDRNOTAVAIL, errno.EHOSTUNREACH):
                    raise CapabilityError('kernel network-denial proof unavailable') from exc
                outcomes.append({'family':family, 'address':address[0], 'errno':exc.errno})
            else:
                raise CapabilityError('network namespace permits external IP connection')
    return {'parent_netns':parent, 'child_netns':current, 'guest_pid':os.getpid(), 'net_dev':Path('/proc/self/net/dev').read_text(),
            'routes':Path('/proc/self/net/route').read_text(), 'ipv6_routes':Path('/proc/self/net/ipv6_route').read_text(), 'external_ip_denials':outcomes,
            'isolation_scope':'OS IP network namespace only; filesystem, AF_UNIX and host peers not isolated'}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('input-file','evidence-root','task-dir'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--decisions-file')
    p.add_argument('--require-authenticated-review', action='store_true')
    p.add_argument('--guest-launch', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--guest-run', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--parent-netns', help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    args = ['--input-file',a.input_file,'--evidence-root',a.evidence_root,'--task-dir',a.task_dir]
    if a.decisions_file:
        args += ['--decisions-file', a.decisions_file]
    if a.require_authenticated_review:
        args += ['--require-authenticated-review']
    try:
        if a.guest_run:
            physical = proof(a.parent_netns)
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import pia_research_loop as loop
            result = loop.run(a.input_file, a.evidence_root, a.task_dir, a.decisions_file, a.require_authenticated_review)
            result['isolation_proof'] = physical
        elif a.guest_launch:
            if os.getuid() == 0:
                raise CapabilityError('root WSL account forbidden; owner must provide an existing nonroot execution context')
            parent = os.readlink('/proc/self/ns/net')
            command = ['/usr/bin/timeout','--kill-after=3',str(GUEST_SECONDS),'/usr/bin/unshare','-Urn',
                       '/usr/bin/python3','-I','-S','-B',str(Path(__file__).resolve()), '--guest-run','--parent-netns',parent,*args]
            result = captured(command, GUEST_SECONDS+8, guest=True)
        else:
            if os.name != 'nt':
                raise ValueError('public isolated-research-loop requires the authorized Windows/WSL host')
            from pia_research_loop import no_links
            for path in (a.input_file,a.evidence_root,a.task_dir,a.decisions_file):
                if path:
                    no_links(Path(path).absolute())
            converted = []
            for index, arg in enumerate(args):
                converted.append(linux_path(arg) if index and args[index-1] in ('--input-file','--evidence-root','--task-dir','--decisions-file') else arg)
            command = ['wsl.exe','--exec','/usr/bin/env','-i','PATH=/usr/bin:/bin','LANG=C.UTF-8',
                       '/usr/bin/python3','-I','-S','-B',linux_path(str(Path(__file__).resolve())), '--guest-launch',*converted]
            result = captured(command, GUEST_SECONDS+18)
    except (ValueError, OSError, UnicodeError, TypeError) as exc:
        detail = ('required_capability_unavailable' if isinstance(exc, (CapabilityError, OSError)) or str(exc).startswith('required_capability_unavailable') else 'isolated_loop_invalid_input_or_result')
        result = {'status':'failed','detail_status':detail,'execution_state':'BLOCKED',
                  'decision_scope':'research_only','host_fallback':False,'errors':[f'{type(exc).__name__}: {exc}']}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return {'complete':0,'incomplete':1,'insufficient_evidence':2,'failed':3}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
