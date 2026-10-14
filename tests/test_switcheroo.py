import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import sys
import psutil  # Load the host backend before tests mock sys.platform.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import switcheroo as s


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'
        self.app = Path(self.temp.name) / 'ChatGPT'
        self.app.touch()
        self.config = {'app': str(self.app), 'profiles': ['default', 'work']}
        s.private_dir(self.root)
        s.save_config(self.root, self.config)
        reader = patch.object(s.account_identity, 'refresh')
        watcher = patch.object(s, 'start_identity_watch')
        reader.start()
        watcher.start()
        self.addCleanup(reader.stop)
        self.addCleanup(watcher.stop)

    def test_profiles_keep_separate_homes(self):
        command, env = s.launch_spec(self.config, self.root, 'work')
        self.assertEqual(command[0], str(self.app))
        self.assertEqual(Path(env['CODEX_HOME']), self.root / 'profiles/work/codex')
        self.assertEqual(Path(env['CODEX_ELECTRON_USER_DATA_PATH']), self.root / 'profiles/work/desktop')
        _, other = s.launch_spec(self.config, self.root, 'personal')
        self.assertNotEqual(env['CODEX_HOME'], other['CODEX_HOME'])
        self.assertFalse((self.root / 'profiles/work/codex/auth.json').exists())

    def confirmed_accounts(self):
        self.config['details'] = {name: {'source': 'app-server', 'status': 'signed-in',
                                        'email': name + '@example.test'}
                                  for name in self.config['profiles']}

    def test_wait_for_window_ignores_other_windows_until_selected_appears(self):
        with patch.object(s, 'open_profiles', side_effect=[{'default'}, {'default', 'work'}]) as windows, patch.object(s.time, 'sleep') as sleep:
            self.assertTrue(s.wait_for_window(self.config, self.root, 'work'))
        windows.assert_called_with(self.config, self.root, windows_only=True)
        sleep.assert_called_once_with(0.25)

    def test_wait_for_window_timeout_does_not_claim_running(self):
        with patch.object(s, 'open_profiles', return_value=set()), patch.object(s.time, 'monotonic', side_effect=[0, 0, 10]), patch.object(s.time, 'sleep') as sleep:
            self.assertFalse(s.wait_for_window(self.config, self.root, 'work'))
        sleep.assert_called_once_with(0.25)

    def test_wait_for_window_skips_wait_if_detection_unavailable(self):
        self.config['_window_status_available'] = False
        with patch.object(s, 'open_profiles', return_value=set()), patch.object(s.time, 'sleep') as sleep:
            self.assertFalse(s.wait_for_window(self.config, self.root, 'work'))
        sleep.assert_not_called()

    def test_quit_targets_only_selected_profile_main_process(self):
        self.confirmed_accounts()
        default, work, child, other = [Mock(pid=pid) for pid in (1, 2, 3, 4)]
        default.cmdline.return_value = [str(self.app)]
        work.cmdline.return_value = [str(self.app), '--user-data-dir', str(self.root / 'profiles/work/desktop')]
        child.cmdline.return_value = work.cmdline.return_value + ['--type=renderer']
        other.cmdline.return_value = [str(self.app), '--user-data-dir=/other/desktop']
        for selected, target in [('work', work), ('default', default)]:
            for process in (default, work, child, other):
                process.reset_mock()
            with patch.object(s.sys, 'platform', 'linux'), patch.object(s, 'app_processes', return_value=[default, work, child, other]):
                self.assertIn('Requested', s.close_account(self.config, self.root, selected))
            target.terminate.assert_called_once_with()
            for process in (default, work, child, other):
                if process is not target:
                    process.terminate.assert_not_called()
                process.kill.assert_not_called()

    def test_quit_closed_account_and_windows_scoping(self):
        self.confirmed_accounts()
        with patch.object(s, 'profile_processes', return_value=[]):
            self.assertIn('already closed', s.close_account(self.config, self.root, 'work'))
        with patch.object(s.sys, 'platform', 'win32'), patch.object(s, 'profile_processes', return_value=[Mock(pid=42)]), patch.object(s.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            s.close_account(self.config, self.root, 'work')
        self.assertIn('Get-Process -Id 42 ', run.call_args.args[0][-1])
        self.assertIn('CloseMainWindow()', run.call_args.args[0][-1])

    def test_quit_all_includes_unlisted_profiles_and_skips_children(self):
        default, removed, child = [Mock(pid=pid) for pid in (1, 2, 3)]
        default.cmdline.return_value = [str(self.app)]
        removed.cmdline.return_value = [str(self.app), '--user-data-dir=/removed/desktop']
        child.cmdline.return_value = [str(self.app), '--type=renderer']
        default.terminate.side_effect = psutil.NoSuchProcess(1)
        with patch.object(s.sys, 'platform', 'linux'), patch.object(s, 'app_processes', return_value=[default, removed, child]):
            self.assertEqual(s.close_account(self.config, self.root, '*'), 'Requested all account windows quit.')
        default.terminate.assert_called_once_with()
        removed.terminate.assert_called_once_with()
        child.terminate.assert_not_called()
        for process in (default, removed, child):
            process.kill.assert_not_called()

    def test_quit_all_windows_requests_every_main_window(self):
        processes = [Mock(pid=pid) for pid in (42, 43)]
        for process in processes:
            process.cmdline.return_value = [str(self.app)]
        with patch.object(s.sys, 'platform', 'win32'), patch.object(s, 'app_processes', return_value=processes), patch.object(s.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            s.close_account(self.config, self.root, '*')
        script = run.call_args.args[0][-1]
        self.assertIn('Get-Process -Id 42,43 ', script)
        self.assertIn('CloseMainWindow()', script)
        self.assertNotIn('{ exit 0 }', script)

    def test_quit_all_when_nothing_running(self):
        with patch.object(s, 'app_processes', return_value=[]):
            self.assertEqual(s.close_account(self.config, self.root, '*'), 'All accounts are already closed.')

    def test_remove_persists_preserves_data_and_does_not_rediscover_default(self):
        self.confirmed_accounts()
        s.launch_spec(self.config, self.root, 'work')
        marker = self.root / 'profiles/work/codex/keep.txt'
        marker.write_text('keep')
        self.config['last_opened'] = 'work'
        with patch.object(s, 'app_processes', return_value=[]) as processes:
            s.remove_account(self.config, self.root, 'work')
            processes.assert_not_called()
        self.assertEqual(self.config['profiles'], ['default'])
        self.assertNotIn('work', self.config['details'])
        self.assertNotIn('last_opened', self.config)
        self.assertEqual(marker.read_text(), 'keep')
        s.remove_account(self.config, self.root, 'default')
        reloaded = json.loads((self.root / 'config.json').read_text())
        with patch.object(s, 'open_profiles', return_value=set()):
            s.refresh_accounts(reloaded, self.root)
        self.assertEqual(reloaded['profiles'], [])
        self.assertEqual(s.account_menu.accounts(reloaded), [])

    def test_remove_save_failure_preserves_config(self):
        self.confirmed_accounts()
        before = json.dumps(self.config)
        with patch.object(s, 'save_config', side_effect=OSError('Disk full')), self.assertRaises(OSError):
            s.remove_account(self.config, self.root, 'work')
        self.assertEqual(json.dumps(self.config), before)

    def test_default_removes_inherited_overrides(self):
        with patch.dict(os.environ, {'CODEX_HOME': 'wrong', 'CODEX_ELECTRON_USER_DATA_PATH': 'wrong', 'CODEX_ACCESS_TOKEN': 'fake', 'OPENAI_API_KEY': 'fake', 'CODEX_SQLITE_HOME': 'wrong'}):
            command, env = s.launch_spec(self.config, self.root, 'default')
        self.assertEqual(command, [str(self.app)])
        self.assertNotIn('CODEX_HOME', env)
        self.assertNotIn('CODEX_ELECTRON_USER_DATA_PATH', env)
        self.assertNotIn('CODEX_ACCESS_TOKEN', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('CODEX_SQLITE_HOME', env)

    def test_rejects_traversal_and_windows_reserved_names(self):
        for name in ('../escape', '/tmp/x', 'Work', 'nul', 'com1', 'aux', 'a b'):
            with self.subTest(name=name), self.assertRaises(s.SwitchError):
                s.valid_name(name)

    def test_dry_run_never_closes_updates_or_launches(self):
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'close_app') as close, patch.object(s, 'check_updates') as update, patch.object(s.subprocess, 'Popen') as launch, contextlib.redirect_stdout(io.StringIO()):
            s.main(['switch', 'work', '--dry-run'])
        close.assert_not_called()
        update.assert_not_called()
        launch.assert_not_called()

    def test_switch_options_work_without_explicit_subcommand(self):
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'choose_profile') as choose, patch.object(s, 'check_updates') as update, contextlib.redirect_stdout(io.StringIO()):
            s.main(['--skip-updates'])
        choose.assert_called_once()
        update.assert_not_called()

    def test_switch_order(self):
        events = []
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'open_profiles', return_value=set()), patch.object(s, 'update_command', return_value=['fake']), patch.object(s, 'close_app', side_effect=lambda _: events.append('close')), patch.object(s, 'check_updates', side_effect=lambda _: events.append('update')), patch.object(s, 'choose_profile', side_effect=lambda *args: events.append('choose')), patch.object(s.subprocess, 'Popen', side_effect=lambda *a, **k: events.append('launch')), contextlib.redirect_stdout(io.StringIO()):
            s.main(['switch'])
        self.assertEqual(events, ['update', 'choose'])

    def test_unknown_profile_does_not_close(self):
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'close_app') as close, self.assertRaises(s.SwitchError):
            s.main(['switch', 'missing'])
        close.assert_not_called()

    def test_lock_releases_and_rejects_concurrency(self):
        if os.name == 'nt':
            self.skipTest('Same-process byte locks have platform-specific semantics')
        with s.locked(self.root):
            with self.assertRaises(s.SwitchError):
                with s.locked(self.root):
                    pass
        with s.locked(self.root):
            pass

    def test_update_available_is_success_on_fedora(self):
        with patch.object(s.sys, 'platform', 'linux'), patch.object(s.shutil, 'which', return_value='/usr/bin/dnf'), patch.object(s.subprocess, 'run', return_value=Mock(returncode=100)), contextlib.redirect_stderr(io.StringIO()) as errors, contextlib.redirect_stdout(io.StringIO()):
            s.check_updates()
        self.assertEqual(errors.getvalue(), '')

    def test_update_failure_does_not_report_success(self):
        with patch.object(s, 'update_command', return_value=['fake']), patch.object(s.subprocess, 'run', return_value=Mock(returncode=1)), contextlib.redirect_stderr(io.StringIO()) as errors, contextlib.redirect_stdout(io.StringIO()):
            s.check_updates()
        self.assertIn('unknown', errors.getvalue())

    def test_windows_update_target(self):
        with patch.object(s.sys, 'platform', 'win32'), patch.object(s.shutil, 'which', return_value='winget'):
            self.assertIn('9PLM9XGG6VKS', s.update_command())
            self.assertIn('--upgrade-available', s.update_command())
            self.assertEqual(s.update_command(True)[1], 'upgrade')

    def test_save_config_atomic_and_private(self):
        self.assertEqual(json.loads((self.root / 'config.json').read_text()), self.config)
        self.assertFalse((self.root / 'config.tmp').exists())
        if os.name != 'nt':
            self.assertEqual((self.root / 'config.json').stat().st_mode & 0o777, 0o600)

    def test_close_timeout_never_force_kills(self):
        process = Mock()
        with patch.object(s, 'app_processes', return_value=[process]), patch.object(s.sys, 'platform', 'linux'), patch.object(s.time, 'monotonic', side_effect=[0, 21]), self.assertRaises(s.SwitchError), contextlib.redirect_stdout(io.StringIO()):
            s.close_app(str(self.app))
        process.terminate.assert_called_once()
        process.kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
