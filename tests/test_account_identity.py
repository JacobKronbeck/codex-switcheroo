import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import account_identity as identity
import switcheroo as s


class IdentityTests(unittest.TestCase):
    def test_only_email_and_plan_are_captured(self):
        data = identity.normalize({'account': {'type': 'chatgpt', 'email': 'user@example.test', 'planType': 'pro', 'accessToken': 'FAKE_SECRET', 'refreshToken': 'FAKE_SECRET', 'username': 'unsupported'}})
        self.assertEqual(data, {'source': 'app-server', 'status': 'signed-in', 'type': 'chatgpt', 'email': 'user@example.test', 'plan': 'pro'})
        self.assertNotIn('FAKE_SECRET', json.dumps(data))

    def test_signed_out_and_api_key_states(self):
        self.assertEqual(identity.normalize({'account': None})['status'], 'signed-out')
        self.assertEqual(identity.normalize({'account': {'type': 'apiKey', 'email': 'ignored'}}), {'source': 'app-server', 'status': 'other-auth', 'type': 'apiKey'})

    def test_real_stdio_handshake_with_fake_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'server.py'
            script.write_text('''import json, sys
message=json.loads(sys.stdin.readline())
assert message['method']=='initialize'
print(json.dumps({'id':1,'result':{}}),flush=True)
assert json.loads(sys.stdin.readline())['method']=='initialized'
request=json.loads(sys.stdin.readline())
assert request['method']=='account/read'
assert request['params']=={'refreshToken':False}
print(json.dumps({'method':'unrelated/notification','params':{}}),flush=True)
print(json.dumps({'id':2,'result':{'account':{'type':'chatgpt','email':'new@example.test','planType':'plus','accessToken':'FAKE_SECRET'}}}),flush=True)
''')
            original = subprocess.Popen
            def fake_launch(command, **kwargs):
                self.assertEqual(command[1:4], ['app-server', '--listen', 'stdio://'])
                return original([sys.executable, str(script)], **kwargs)
            with patch.object(identity.subprocess, 'Popen', side_effect=fake_launch):
                result = identity.read_account('fake-codex', dict(os.environ, CODEX_HOME=str(root)))
            self.assertEqual(result['email'], 'new@example.test')
            self.assertNotIn('FAKE_SECRET', json.dumps(result))

    def test_timeout_terminates_only_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / 'server.py'
            script.write_text('import time; time.sleep(60)')
            original = subprocess.Popen
            children = []
            def fake_launch(command, **kwargs):
                child = original([sys.executable, str(script)], **kwargs)
                children.append(child)
                return child
            with patch.object(identity.subprocess, 'Popen', side_effect=fake_launch), self.assertRaises(identity.IdentityUnavailable):
                identity.read_account('fake', dict(os.environ, CODEX_HOME=temporary), timeout=0.1)
            self.assertIsNotNone(children[0].poll())

    def test_missing_reader_does_not_reuse_manual_labels(self):
        config = {'profiles': ['default'], 'details': {'default': {'email': 'manual@example.test'}}}
        with patch.object(identity, 'discover', side_effect=identity.IdentityUnavailable):
            identity.refresh(config, Path('/fake'), Mock())
        self.assertNotIn('email', config['details']['default'])

    def test_uninitialized_profile_never_probes_default_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = {'profiles': ['new']}
            launch = Mock()
            with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'read_account') as read:
                identity.refresh(config, Path(temporary), launch)
            read.assert_not_called()
            launch.assert_not_called()
            self.assertEqual(config['details']['new']['status'], 'signed-out')

    def test_watcher_stops_if_profile_was_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            s.save_config(root, {'profiles': ['default'], 'last_opened': 'default'})
            with patch.object(identity, 'refresh') as refresh:
                s.watch_identity(root, 'new', duration=1)
            refresh.assert_not_called()

    def test_watcher_saves_first_login_automatically(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            s.save_config(root, {'profiles': ['new'], 'last_opened': 'new'})
            def refresh(config, *args, **kwargs):
                config['details'] = {'new': {'source': 'app-server', 'status': 'signed-in', 'email': 'new@example.test', 'plan': 'plus'}}
            with patch.object(identity, 'refresh', side_effect=refresh):
                s.watch_identity(root, 'new', duration=1)
            config = json.loads((root / 'config.json').read_text())
            self.assertEqual(config['details']['new']['email'], 'new@example.test')


if __name__ == '__main__':
    unittest.main()
