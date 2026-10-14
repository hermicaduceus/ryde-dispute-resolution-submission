"""Behavioural pins for the reproduced W47 independent-review follow-ups."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.test_w47_live_launcher import (
    _load_live, _run_main, _sidecar, _valid_lines,
)
from tests.test_w47_submission_package import load_packager_module

REPO=Path(__file__).resolve().parents[1]


class ReadinessAndShutdown(unittest.TestCase):
    def setUp(self):
        self.m=_load_live(self)

    def test_browser_opens_only_after_successful_readiness(self):
        events=[]
        statuses=iter([None,503,200])
        def answer(url):
            value=next(statuses)
            events.append(('answer',value))
            return value
        def opening(url):
            events.append(('open',url))
            return True
        with mock.patch.object(self.m,'_answer',answer), mock.patch.object(self.m,'_open',opening), \
             mock.patch.object(self.m.time,'sleep',lambda delay:None):
            self.m.open_when_ready('http://127.0.0.1:8030/party/',timeout=30)
        self.assertEqual([('answer',None),('answer',503),('answer',200),
                          ('open','http://127.0.0.1:8030/party/')],events)

    def test_readiness_timeout_gives_manual_url_without_opening(self):
        url='http://127.0.0.1:8030/party/'
        out=io.StringIO()
        with mock.patch.object(self.m,'_answer',return_value=None), \
             mock.patch.object(self.m,'_open') as opening, \
             mock.patch.object(self.m.time,'monotonic',side_effect=[0,1]), \
             contextlib.redirect_stdout(out):
            self.m.open_when_ready(url,timeout=.5)
        opening.assert_not_called()
        self.assertIn(url,out.getvalue())

    def test_browser_open_failure_gives_manual_url(self):
        url='http://127.0.0.1:8030/party/'
        out=io.StringIO()
        with mock.patch.object(self.m,'_answer',return_value=200), \
             mock.patch.object(self.m,'_open',return_value=False) as opening, \
             contextlib.redirect_stdout(out):
            self.m.open_when_ready(url)
        opening.assert_called_once_with(url)
        self.assertIn(url,out.getvalue())

    def test_normal_return_closes_owned_server(self):
        path=_sidecar(self,_valid_lines())
        with mock.patch.dict(os.environ,dict(os.environ),clear=True):
            rc,lines,calls,httpd=_run_main(self,self.m,['--credentials',str(path)])
        self.assertEqual(0,rc)
        self.assertTrue(httpd.served)
        self.assertTrue(httpd.closed,'owned server_close must run even on normal return')


class PackagingAndFilming(unittest.TestCase):
    def setUp(self):
        self.assertTrue((REPO/'tools/package_submission.py').is_file(),'packager is absent')
        self.m=load_packager_module()

    def test_bare_json_placeholder_and_near_misses(self):
        header=b'Authorization'+b': Bearer '
        good=json.dumps({'content':(header+b'<KEY>').decode()}).encode()
        self.assertEqual([],self.m.content_refusals('evidence/example.jsonl',good))
        fake=b'FAKE0' + b'W47ReviewTokenNotReal'
        for value in (fake,b'<KEY>'+fake,b'<'+fake+b'>'):
            body=json.dumps({'content':(header+value).decode()}).encode()
            self.assertTrue(self.m.content_refusals('evidence/example.jsonl',body))

    def test_bare_private_key_names_and_public_counterparts(self):
        for name in ('id_rsa','id_ed25519','id_ecdsa','id_dsa'):
            for variant in (name,name.upper()):
                self.assertIsNotNone(self.m._credential_path_reason('keys/'+variant))
            self.assertIsNone(self.m._credential_path_reason('keys/'+name+'.pub'))

    def test_filming_labels_are_explicit(self):
        text=(REPO/'docs/live-copy.md').read_text()
        self.assertIn('Waiting time shortened',text)
        self.assertIn('Replay of saved run',text)
        self.assertRegex(text.lower(),r'replay[^\n]*date|date[^\n]*replay')


class MacArguments(unittest.TestCase):
    def test_actual_wrapper_preserves_argument_boundaries(self):
        tmp=Path(tempfile.mkdtemp(prefix='w47-wrapper space 例子-'))
        self.addCleanup(shutil.rmtree,tmp)
        script=tmp/'start-live.command'
        source=REPO/'start-live.command'
        self.assertTrue(source.is_file(),'Mac wrapper is absent')
        shutil.copy2(source,script)
        bindir=tmp/'bin';bindir.mkdir()
        record=tmp/'argv.json'
        fake=bindir/'python3'
        fake.write_text('#!'+sys.executable+'\nimport json,os,sys\nfrom pathlib import Path\n'
                        'if len(sys.argv)>1 and sys.argv[1]=="-c":sys.exit(0)\n'
                        'Path(os.environ["W47_ARGV_FILE"]).write_text(json.dumps(sys.argv[1:]))\n')
        fake.chmod(0o755)
        env=dict(os.environ);env['PATH']=str(bindir)+':/usr/bin:/bin';env['W47_ARGV_FILE']=str(record)
        args=['--port','8040','--credentials','private space 例子/file']
        p=subprocess.run(['/bin/bash',str(script)]+args,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(0,p.returncode,p.stderr)
        self.assertTrue(record.is_file(),'wrapper did not execute interpreter')
        self.assertEqual(['tools/launch_live.py']+args,json.loads(record.read_text()))


if __name__=='__main__':
    unittest.main()
