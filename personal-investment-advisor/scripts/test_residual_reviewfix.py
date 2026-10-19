"""Synthetic anonymous transport and owned deadline regression probes; no real credentials."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.request import Request

import requests
import secure_transport as transport
import evidence_channels as ec
import pia_isolated_loop as isolated
from test_p2_evidence_channels import FakeSession, FakeResponse


class AnonymousTests(unittest.TestCase):
    def test_no_implicit_netrc_proxy_or_auth_preparation(self):
        session=requests.Session()
        seen=[]
        def send(prepared, **kwargs):
            seen.append(prepared)
            r=requests.Response();r.status_code=200;r._content=b'{}';return r
        with mock.patch('requests.sessions.get_netrc_auth',return_value=('synthetic','synthetic')) as netrc, mock.patch('requests.sessions.get_environ_proxies',return_value={}) as proxies, mock.patch.object(session,'send',side_effect=send):
            transport.request(session,'GET','https://example.test/anonymous')
        netrc.assert_not_called();proxies.assert_not_called()
        self.assertFalse(session.trust_env)
        self.assertFalse(set(seen[0].headers)&{'Authorization','Proxy-Authorization','Cookie'})

    def test_explicit_credentials_rejected_without_send(self):
        for kwargs in ({'auth':('synthetic','synthetic')},{'cookies':{'synthetic':'synthetic'}},{'cert':'synthetic'},{'headers':{'Authorization':'synthetic'}},{'headers':{'Proxy-Authorization':'synthetic'}},{'headers':{'Cookie':'synthetic'}}):
            with requests.Session() as s, mock.patch.object(s,'send') as send:
                with self.subTest(keys=list(kwargs)), self.assertRaises(ValueError):transport.request(s,'GET','https://example.test',**kwargs)
                send.assert_not_called()
        for field,value in (('auth',('synthetic','synthetic')),('headers',{'Authorization':'synthetic'}),('cert','synthetic'),('proxies',{'https':'synthetic'})):
            with requests.Session() as s, mock.patch.object(s,'send') as send:
                setattr(s,field,value)
                with self.assertRaises(ValueError):transport.request(s,'GET','https://example.test')
                send.assert_not_called()

    def test_cookie_not_reused_across_public_calls(self):
        with transport.anonymous_session() as s:
            def send(prepared, **kwargs):
                self.assertNotIn('Cookie',prepared.headers)
                s.cookies.set('synthetic','synthetic')
                r=requests.Response();r.status_code=200;r._content=b'{}';return r
            with mock.patch.object(s,'send',side_effect=send):
                transport.request(s,'GET','https://example.test')
                transport.request(s,'GET','https://example.test')
            self.assertFalse(s.cookies)

    def test_urllib_no_environment_proxy_or_auth_header(self):
        with mock.patch.dict(os.environ,{'https_proxy':'http://synthetic:synthetic@example.invalid:80'}), mock.patch('urllib.request.getproxies') as proxies, mock.patch.object(transport,'build_opener') as builder:
            transport.open_https(Request('https://example.test'),1)
            proxies.assert_not_called()
            self.assertEqual(builder.call_args.args[2].proxies,{})
        with self.assertRaises(ValueError):transport.open_https(Request('https://example.test',headers={'Authorization':'synthetic'}),1)

    def test_old_cache_policy_and_schema_refetch_preserve_time(self):
        for mutation in ('schema','policy'):
            with tempfile.TemporaryDirectory() as d:
                s=FakeSession([FakeResponse(200,b'old'),FakeResponse(200,b'new')]);clock=[100]
                f=ec.ChannelFetcher(session=s,cache_dir=Path(d),clock=lambda:clock[0])
                f.request('GET','https://example.test',key='k')
                p=next(Path(d).glob('*.cache.json'));data=json.loads(p.read_text())
                if mutation=='schema':data['version']=2
                else:
                    data['meta']['anonymous_policy']='legacy';data['meta_sha256']=ec.sha256_bytes(json.dumps(data['meta'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
                p.write_text(json.dumps(data));clock[0]=101
                result=f.request('GET','https://example.test',key='k')
                self.assertFalse(result['reused']);self.assertEqual(result['body'],b'new')
                clock[0]=102
                reused=f.request('GET','https://example.test',key='k')
                self.assertTrue(reused['reused']);self.assertEqual(reused['fetched_at'],101)


class DeadlineTests(unittest.TestCase):
    def test_windows_outer_timeout_kills_exact_handle_and_reaps(self):
        process=mock.Mock();process.wait.side_effect=[subprocess.TimeoutExpired('fixed',.1),0]
        with mock.patch.object(isolated.subprocess,'Popen',return_value=process):
            with self.assertRaisesRegex(isolated.CapabilityError,'deadline'):
                isolated.captured(['fixed'],.1)
        process.kill.assert_called_once();self.assertEqual(process.wait.call_count,2)

    def test_guest_timeout_uses_owned_group_only(self):
        process=mock.Mock();process.pid=321;process.wait.side_effect=[subprocess.TimeoutExpired('fixed',.1),0]
        with mock.patch.object(isolated.subprocess,'Popen',return_value=process),mock.patch.object(isolated.os,'killpg',create=True) as kill, mock.patch.object(isolated.signal,'SIGKILL',9,create=True):
            with self.assertRaises(isolated.CapabilityError):isolated.captured(['fixed'],.1,guest=True)
        kill.assert_called_once_with(321,9);process.kill.assert_not_called()


if __name__=='__main__':unittest.main()
