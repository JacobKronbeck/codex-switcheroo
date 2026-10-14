import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import account_identity as identity
import switcheroo as s


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'app': str(self.root / 'app'), 'profiles': ['default']}
        Path(self.config['app']).touch()
        self.metadata = {'source': 'app-server', 'status': 'signed-in', 'email': 'new@example.test'}

    def test_enrollment_registers_only_after_confirmation_and_scopes_credentials(self):
        def login(exe, env, **kwargs):
            self.assertEqual(self.config['profiles'], ['default'])
            self.assertIn('cli_auth_credentials_store = "file"', (Path(env['CODEX_HOME']) / 'config.toml').read_text())
            return dict(self.metadata)
        with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', side_effect=login), contextlib.redirect_stdout(io.StringIO()):
            name = s.enroll_account(self.config, self.root)
        self.assertTrue(name.startswith('account-'))
        self.assertTrue(self.config['details'][name]['confirmed'])
        self.assertIn(name, json.loads((self.root / 'config.json').read_text())['profiles'])

    def test_failed_cancelled_and_timed_out_enrollment_do_not_register(self):
        for error in (identity.IdentityUnavailable('failed'), identity.IdentityUnavailable('timed out')):
            with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(s.enroll_account(self.config, self.root, 'new'))
            self.assertEqual(self.config['profiles'], ['default'])
            self.assertFalse((self.root / 'profiles/new').exists())

    def test_duplicate_workspace_reuses_existing_account(self):
        self.metadata['workspace_id'] = 'workspace-1'
        self.config['details'] = {'default': dict(self.metadata, email='NEW@example.test')}
        with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', return_value=dict(self.metadata)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.enroll_account(self.config, self.root, 'new'), 'default')
        self.assertEqual(self.config['profiles'], ['default'])
        self.assertFalse((self.root / 'profiles/new').exists())

    def test_same_email_different_or_unknown_workspace_keeps_new_profile(self):
        for existing_id, new_id in [('work', 'personal'), (None, 'personal'), ('work', None), (None, None)]:
            with self.subTest(existing_id=existing_id, new_id=new_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config = dict(self.config, profiles=['default'], details={
                    'default': dict(self.metadata, workspace_id=existing_id)})
                metadata = dict(self.metadata, workspace_id=new_id)
                with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', return_value=metadata), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(s.enroll_account(config, root, 'new', workspace='Personal account'), 'new')
                self.assertEqual(config['profiles'], ['default', 'new'])
                self.assertTrue((root / 'profiles/new/codex').is_dir())
                self.assertEqual(config['details']['new']['workspace_label'], 'Personal account')

    def test_interactive_enrollment_offers_workspace_label(self):
        with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', return_value=dict(self.metadata)), patch.object(s.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='Alliant Engineering'), contextlib.redirect_stdout(io.StringIO()):
            name = s.enroll_account(self.config, self.root)
        self.assertEqual(self.config['details'][name]['workspace_label'], 'Alliant Engineering')

    def test_open_refreshes_then_activates_without_duplicate_launch(self):
        with patch.object(s, 'refresh_accounts', return_value={'default'}) as refresh, patch.object(s, 'activate_profile', return_value=True) as activate, patch.object(s.subprocess, 'Popen') as launch, patch.object(s, 'close_app') as close, contextlib.redirect_stdout(io.StringIO()):
            s.open_account(self.config, self.root, 'default')
        refresh.assert_called_once()
        activate.assert_called_once()
        launch.assert_not_called()
        close.assert_not_called()

    def test_background_account_reopens_same_profile_when_activation_fails(self):
        for selected in ('default', 'work'):
            with self.subTest(profile=selected):
                self.config['profiles'] = ['default', 'work']
                with patch.object(s, 'wait_for_window', return_value=False), patch.object(s, 'refresh_accounts', return_value={selected}), patch.object(s, 'activate_profile', return_value=False), patch.object(s.subprocess, 'Popen') as launch, patch.object(s, 'start_identity_watch'), patch.object(s, 'close_app') as close, contextlib.redirect_stdout(io.StringIO()) as out:
                    s.open_account(self.config, self.root, selected)
                launch.assert_called_once()
                command = launch.call_args.args[0]
                env = launch.call_args.kwargs['env']
                if selected == 'default':
                    self.assertEqual(command, [self.config['app']])
                    self.assertNotIn('CODEX_ELECTRON_USER_DATA_PATH', env)
                else:
                    desktop = str(self.root / 'profiles/work/desktop')
                    self.assertEqual(command, [self.config['app'], '--user-data-dir=' + desktop])
                    self.assertEqual(env['CODEX_ELECTRON_USER_DATA_PATH'], desktop)
                    self.assertEqual(env['CODEX_HOME'], str(self.root / 'profiles/work/codex'))
                self.assertIn('Requested window reopen', out.getvalue())
                self.assertNotIn('already open', out.getvalue())
                close.assert_not_called()

    def test_background_account_reopen_reports_launch_failure(self):
        with patch.object(s, 'refresh_accounts', return_value={'default'}), patch.object(s, 'activate_profile', return_value=False), patch.object(s.subprocess, 'Popen', side_effect=OSError('failed')), self.assertRaises(s.SwitchError):
            s.open_account(self.config, self.root, 'default')

    def test_cli_add_opens_immediately(self):
        s.save_config(self.root, self.config)
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'refresh_accounts'), patch.object(s, 'enroll_account', return_value='default'), patch.object(s, 'open_account') as opened, patch.object(s, 'choose_profile'):
            s.main(['add'])
        opened.assert_called_once_with(self.config, self.root, 'default')

    def test_cancel_preserves_windows(self):
        s.save_config(self.root, self.config)
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'choose_profile', return_value=None), patch.object(s, 'close_app') as close, patch.object(s.subprocess, 'Popen') as launch:
            s.main(['switch', '--skip-updates'])
        close.assert_not_called()
        launch.assert_not_called()

    def test_update_install_refuses_when_any_app_process_runs(self):
        s.save_config(self.root, self.config)
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'app_processes', return_value=[Mock()]), patch.object(s, 'check_updates') as update, patch.object(s, 'close_app') as close, self.assertRaises(s.SwitchError):
            s.main(['switch', '--install-updates'])
        update.assert_not_called()
        close.assert_not_called()

    def test_discovery_and_signed_out_refresh_retain_confirmed_identity(self):
        self.config['profiles'] = []
        def refresh(config, root, launch):
            self.assertIn('default', config['profiles'])
            config['details'] = {'default': dict(self.metadata)}
        with patch.object(identity, 'refresh', side_effect=refresh), patch.object(s, 'open_profiles', return_value=set()):
            s.refresh_accounts(self.config, self.root)
        self.assertEqual(s.account_menu.accounts(self.config), ['default'])
        remembered = identity.remembered(self.metadata, {'source': 'app-server', 'status': 'signed-out'})
        self.assertEqual(remembered['email'], 'new@example.test')
        self.assertTrue(remembered['confirmed'])
        with patch.object(identity, 'discover', side_effect=identity.IdentityUnavailable()):
            identity.refresh(self.config, self.root, Mock())
        self.assertEqual(self.config['details']['default']['status'], 'unavailable')
        self.assertEqual(self.config['details']['default']['email'], 'new@example.test')

    def run_protocol(self, outcome='success', opener=None, timeout=2, check_cancel=None):
        script = self.root / 'server.py'
        script.write_text('''import json,sys,time
read=lambda:json.loads(sys.stdin.readline())
send=lambda m:print(json.dumps(m),flush=True)
assert read()['method']=='initialize'
send({'id':1,'result':{}})
assert read()['method']=='initialized'
assert read()['method']=='account/login/start'
# Completion can arrive before the start response and unrelated IDs must be ignored.
send({'method':'account/login/completed','params':{'loginId':'other','success':True}})
''' + ('''send({'method':'account/login/completed','params':{'loginId':'ours','success':True}})
''' if outcome == 'success' else ("send({'method':'account/login/completed','params':{'loginId':'ours','success':False,'error':'FAKE_SECRET'}})\n" if outcome == 'failure' else '')) + '''send({'id':2,'result':{'loginId':'ours','authUrl':'https://auth.openai.com/fake'}})
''' + ('''assert read()['method']=='account/read'
send({'id':3,'result':{'account':{'type':'chatgpt','email':'new@example.test','accessToken':'FAKE_SECRET'}}})
''' if outcome == 'success' else '''time.sleep(60)
'''))
        original = subprocess.Popen
        children = []
        def launch(command, **kwargs):
            child = original([sys.executable, str(script)], **kwargs)
            children.append(child)
            return child
        try:
            with patch.object(identity.subprocess, 'Popen', side_effect=launch), contextlib.redirect_stdout(io.StringIO()) as out:
                result = identity.login('fake', dict(os.environ, CODEX_HOME=str(self.root)), timeout=timeout, open_browser=opener or Mock(return_value=True), check_cancel=check_cancel)
            return result, out.getvalue()
        finally:
            for child in children:
                self.assertIsNotNone(child.poll())

    def test_protocol_early_notification_and_failed_browser_open(self):
        result, output = self.run_protocol(opener=Mock(return_value=False))
        self.assertEqual(result['email'], 'new@example.test')
        self.assertIn('https://auth.openai.com/fake', output)
        self.assertNotIn('FAKE_SECRET', output + json.dumps(result))

    def test_protocol_timeout_cleans_up_helper(self):
        with self.assertRaises(identity.IdentityUnavailable):
            self.run_protocol(outcome='timeout', timeout=0.1)

    def test_protocol_interrupt_cleans_up_helper(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_protocol(opener=Mock(side_effect=KeyboardInterrupt))

    def test_protocol_failed_completion_does_not_expose_raw_error(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(identity.IdentityUnavailable) as error:
            self.run_protocol(outcome='failure')
        self.assertNotIn('FAKE_SECRET', str(error.exception) + out.getvalue())

    def test_save_failure_rolls_back_new_account(self):
        with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', return_value=dict(self.metadata)), patch.object(s, 'save_config', side_effect=OSError('cannot save')), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(s.enroll_account(self.config, self.root, 'new'))
        self.assertEqual(self.config['profiles'], ['default'])
        self.assertNotIn('new', self.config.get('details', {}))
        self.assertFalse((self.root / 'profiles/new').exists())

    def test_enrollment_legacy_name_and_new_window_launch(self):
        with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', return_value=dict(self.metadata)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.enroll_account(self.config, self.root, 'work'), 'work')
        with patch.object(s, 'wait_for_window', return_value=False), patch.object(s, 'refresh_accounts', return_value={'default'}), patch.object(s.subprocess, 'Popen') as launch, patch.object(s, 'start_identity_watch'), patch.object(s, 'close_app') as close, contextlib.redirect_stdout(io.StringIO()):
            s.open_account(self.config, self.root, 'work')
        self.assertIn('--user-data-dir=' + str(self.root / 'profiles/work/desktop'), launch.call_args.args[0])
        close.assert_not_called()

    def test_picker_waits_for_new_window_and_shows_running_without_refresh_input(self):
        self.config['details'] = {'default': dict(self.metadata)}
        s.save_config(self.root, self.config)
        with patch.object(identity, 'refresh'), patch.object(s, 'open_profiles', side_effect=[set(), set(), set(), set(), {'default'}, {'default'}]), patch.object(s.subprocess, 'Popen') as launch, patch.object(s, 'start_identity_watch'), patch.object(s.time, 'sleep') as sleep, patch('builtins.input', side_effect=['1', 'q']), contextlib.redirect_stdout(io.StringIO()) as out:
            s.choose_profile(self.config, self.root)
        launch.assert_called_once()
        sleep.assert_called_once_with(0.25)
        self.assertIn('Account window is running: new@example.test.', out.getvalue())
        self.assertIn('● new@example.test', out.getvalue())

    def test_linux_activation_targets_profile_window(self):
        self.config['profiles'].append('work')
        process = Mock(pid=123)
        process.cmdline.return_value = [self.config['app'], '--user-data-dir=' + str(self.root / 'profiles/work/desktop')]
        with patch.object(s.sys, 'platform', 'linux'), patch.object(s, 'app_processes', return_value=[process]), patch.object(s.shutil, 'which', return_value='/fake/wmctrl'), patch.object(s.subprocess, 'run', side_effect=[Mock(stdout='0x123 0 123 host title\n', returncode=0), Mock(returncode=0)]) as run:
            self.assertTrue(s.activate_profile(self.config, self.root, 'work'))
        self.assertEqual(run.call_args.args[0], ['wmctrl', '-ia', '0x123'])

    def test_windows_activation_uses_only_matching_pids(self):
        process = Mock(pid=123)
        process.cmdline.return_value = [self.config['app']]
        with patch.object(s.sys, 'platform', 'win32'), patch.object(s, 'app_processes', return_value=[process]), patch.object(s.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertTrue(s.activate_profile(self.config, self.root, 'default'))
        self.assertIn('Get-Process -Id 123', run.call_args.args[0][-1])
        self.assertIn('SetForegroundWindow', run.call_args.args[0][-1])

    def test_launcher_wrapper_matches_desktop_process_without_cli_helpers(self):
        launcher = self.root / 'codex-launcher'
        desktop = self.root / 'ChatGPT'
        launcher.touch()
        desktop.touch()
        first, helper, other = Mock(), Mock(), Mock()
        first.info = {'exe': str(desktop)}
        helper.info = {'exe': str(self.root / 'resources/codex')}
        other.info = {'exe': '/different/ChatGPT'}
        import psutil
        with patch.object(psutil, 'process_iter', return_value=[first, helper, other]):
            self.assertEqual(s.app_processes(str(launcher)), [first])

    def test_persistent_picker_does_not_hold_lock_while_waiting(self):
        s.save_config(self.root, self.config)
        def answer(prompt):
            with s.locked(self.root):
                pass
            return 'q'
        with patch.object(s, 'state_root', return_value=self.root), patch.object(identity, 'refresh'), patch.object(s, 'open_profiles', return_value=set()), patch('builtins.input', side_effect=answer), contextlib.redirect_stdout(io.StringIO()):
            s.main(['switch', '--skip-updates'])

    def test_ctrl_c_enrollment_propagates_and_removes_unregistered_profile(self):
        with patch.object(identity, 'discover', return_value='fake'), patch.object(identity, 'login', side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            s.enroll_account(self.config, self.root, 'new')
        self.assertEqual(self.config['profiles'], ['default'])
        self.assertFalse((self.root / 'profiles/new').exists())

    def test_picker_label_edits_persist_after_refresh_and_restart(self):
        self.config['details'] = {'default': dict(self.metadata, workspace_id='workspace-1')}
        s.save_config(self.root, self.config)
        def refresh(config, root, launch):
            config['details']['default'] = identity.remembered(config['details']['default'], dict(self.metadata, workspace_id='workspace-1'))
        for label in ['My workspace', '']:
            with patch.object(identity, 'refresh', side_effect=refresh), patch.object(s, 'open_profiles', return_value=set()), patch('builtins.input', side_effect=['e', '1', label, 'r', 'q']), contextlib.redirect_stdout(io.StringIO()):
                s.choose_profile(self.config, self.root)
            saved = json.loads((self.root / 'config.json').read_text())
            self.assertEqual(saved['details']['default'].get('workspace_label', ''), label)
            self.assertEqual(saved['details']['default']['email'], self.metadata['email'])
            self.assertEqual(saved['details']['default']['workspace_id'], 'workspace-1')
            self.config = saved

    def test_protocol_back_cancels_and_cleans_up_helper(self):
        import account_menu
        with self.assertRaises(account_menu.BackRequested):
            self.run_protocol(outcome='timeout', check_cancel=Mock(side_effect=account_menu.BackRequested()))

    def test_cli_picker_repeated_selection_refresh_back_quit(self):
        self.config['details'] = {'default': dict(self.metadata)}
        s.save_config(self.root, self.config)
        with patch.object(s, 'state_root', return_value=self.root), patch.object(identity, 'refresh'), patch.object(s, 'open_profiles', return_value={'default'}), patch.object(s, 'activate_profile', return_value=True) as activate, patch.object(s.subprocess, 'Popen') as launch, patch('builtins.input', side_effect=['1', 'r', 'b', '1', 'q']), contextlib.redirect_stdout(io.StringIO()) as out:
            s.main(['switch', '--skip-updates'])
        self.assertEqual(activate.call_count, 2)
        launch.assert_not_called()
        self.assertEqual(out.getvalue().count('Account window activated.'), 2)
        self.assertIn('q. Quit', out.getvalue())
