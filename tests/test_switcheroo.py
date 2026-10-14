import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import sys
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

    def test_profiles_keep_separate_homes(self):
        command, env = s.launch_spec(self.config, self.root, 'work')
        self.assertEqual(command[0], str(self.app))
        self.assertEqual(Path(env['CODEX_HOME']), self.root / 'profiles/work/codex')
        self.assertEqual(Path(env['CODEX_ELECTRON_USER_DATA_PATH']), self.root / 'profiles/work/desktop')
        _, other = s.launch_spec(self.config, self.root, 'personal')
        self.assertNotEqual(env['CODEX_HOME'], other['CODEX_HOME'])
        self.assertFalse((self.root / 'profiles/work/codex/auth.json').exists())

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

    def test_switch_order(self):
        events = []
        with patch.object(s, 'state_root', return_value=self.root), patch.object(s, 'update_command', return_value=['fake']), patch.object(s, 'close_app', side_effect=lambda _: events.append('close')), patch.object(s, 'check_updates', side_effect=lambda _: events.append('update')), patch.object(s, 'choose_profile', side_effect=lambda _: events.append('choose') or 'work'), patch.object(s.subprocess, 'Popen', side_effect=lambda *a, **k: events.append('launch')), contextlib.redirect_stdout(io.StringIO()):
            s.main(['switch'])
        self.assertEqual(events, ['close', 'update', 'choose', 'launch'])

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
