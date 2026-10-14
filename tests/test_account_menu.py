import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import account_menu as menu
import switcheroo as s


class AccountMenuTests(unittest.TestCase):
    def test_same_email_workspaces_have_separate_numbers_and_open_status(self):
        config = {'profiles': ['work', 'personal'], 'details': {
            name: {'source': 'app-server', 'status': 'signed-in', 'email': 'user@example.test',
                   'workspace_label': label} for name, label in [('work', 'Alliant Engineering'), ('personal', 'Personal account')]}}
        with patch.object(menu, 'green', side_effect=lambda value: value), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.show(config, {'personal'}), ['work', 'personal'])
        self.assertIn('1. user@example.test — Alliant Engineering', out.getvalue())
        self.assertIn('2. ● user@example.test — Personal account', out.getvalue())
        with patch('builtins.input', side_effect=['2', 'q']), contextlib.redirect_stdout(io.StringIO()):
            opened = Mock()
            menu.choose(config, Mock(return_value=set()), Mock(), opened)
        opened.assert_called_once_with('personal')

    def setUp(self):
        self.config = {'app': '/fake/app', 'profiles': ['default', 'personal'], 'details': {'personal': {'source': 'app-server', 'status': 'signed-in', 'email': 'user@example.test', 'plan': 'pro'}}}

    def test_number_selection_hides_presets_and_extra_details(self):
        refresh = Mock(return_value=set())
        with patch('builtins.input', side_effect=['1', 'q']), contextlib.redirect_stdout(io.StringIO()) as out:
            opened = Mock()
            result = menu.choose(self.config, refresh, Mock(), opened)
        self.assertIsNone(result)
        opened.assert_called_once_with('personal')
        self.assertIn('1. user@example.test', out.getvalue())
        self.assertIn('a. Add account', out.getvalue())
        for value in ('default', 'personal', 'Plan:', 'Organization:', 'last opened'):
            self.assertNotIn(value, out.getvalue())
        self.assertEqual(refresh.call_count, 2)

    def test_successful_add_selects_confirmed_account(self):
        enroll = Mock(return_value='new')
        with patch('builtins.input', side_effect=['a', 'q']), contextlib.redirect_stdout(io.StringIO()):
            opened = Mock()
            self.assertIsNone(menu.choose(self.config, Mock(return_value=set()), enroll, opened))
            opened.assert_called_once_with('new')
        enroll.assert_called_once_with()

    def test_failed_add_returns_to_refreshed_picker(self):
        refresh = Mock(return_value=set())
        with patch('builtins.input', side_effect=['a', 'q']), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(menu.choose(self.config, refresh, Mock(return_value=None), Mock()))
        self.assertEqual(refresh.call_count, 2)

    def test_old_empty_config_shows_no_accounts(self):
        self.config.pop('details')
        with patch('builtins.input', return_value='q'), contextlib.redirect_stdout(io.StringIO()) as out:
            menu.choose(self.config, Mock(return_value=set()), Mock(), Mock())
        self.assertIn('No accounts', out.getvalue())
        self.assertIn('Add an account to get started', out.getvalue())

    def test_stale_and_signed_out_accounts_remain_without_green(self):
        detail = self.config['details']['personal']
        detail['confirmed'] = True
        for status in ('signed-out', 'unavailable'):
            detail['status'] = status
            with patch.object(menu, 'green') as green, contextlib.redirect_stdout(io.StringIO()) as out:
                menu.show(self.config, {'personal'})
            green.assert_not_called()
            self.assertIn('user@example.test', out.getvalue())
            self.assertNotIn('[open]', out.getvalue())

    def test_green_dot_and_email_for_all_open_accounts(self):
        self.config['details']['default'] = dict(self.config['details']['personal'], email='second@example.test')
        with patch.object(menu, 'green', side_effect=lambda value: '<green>' + value) as green, contextlib.redirect_stdout(io.StringIO()) as out:
            menu.show(self.config, {'default', 'personal'})
        self.assertEqual(green.call_count, 2)
        self.assertIn('<green>● user@example.test', out.getvalue())
        self.assertIn('<green>● second@example.test', out.getvalue())

    def test_plain_terminal_shows_open_marker(self):
        with patch.object(menu, 'green', side_effect=lambda value: value), contextlib.redirect_stdout(io.StringIO()) as out:
            menu.show(self.config, {'personal'})
        self.assertIn('● user@example.test [open]', out.getvalue())

    def test_terminal_controls_are_removed(self):
        self.assertEqual(menu.clean('Name\n\033\t'), 'Name')

    def test_color_only_for_tty_and_respects_no_color(self):
        with patch.object(menu.os, 'name', 'posix'), patch.object(menu.sys.stdout, 'isatty', return_value=True), patch.dict(menu.os.environ, {'TERM': 'xterm'}, clear=True):
            self.assertEqual(menu.green('User'), '\033[32mUser\033[0m')
            with patch.dict(menu.os.environ, {'NO_COLOR': '1'}):
                self.assertEqual(menu.green('User'), 'User')
        with patch.object(menu.sys.stdout, 'isatty', return_value=False):
            self.assertEqual(menu.green('User'), 'User')

    def test_multiple_open_profiles_detected_and_children_ignored(self):
        root = Path('/fake').resolve()
        first, second, child = Mock(), Mock(), Mock()
        first.cmdline.return_value = ['/fake/app']
        second.cmdline.return_value = ['/fake/app', '--user-data-dir', str(root / 'profiles/personal/desktop')]
        child.cmdline.return_value = ['/fake/app', '--type=renderer']
        with patch.object(s, 'app_processes', return_value=[first, second, child]):
            self.assertEqual(s.open_profiles(self.config, root), {'default', 'personal'})
        with patch.object(s, 'app_processes', return_value=[]):
            self.assertEqual(s.open_profiles(self.config, root), set())

    def test_last_opened_never_claimed_open(self):
        self.config['last_opened'] = 'personal'
        with patch.object(menu, 'green') as green, contextlib.redirect_stdout(io.StringIO()) as out:
            menu.show(self.config)
        green.assert_not_called()
        self.assertNotIn('[open]', out.getvalue())
        self.assertNotIn('last opened', out.getvalue())

    def test_background_process_does_not_count_as_open_window(self):
        root = Path('/fake').resolve()
        process = Mock(pid=123)
        process.cmdline.return_value = ['/fake/app', '--user-data-dir=' + str(root / 'profiles/personal/desktop')]
        with patch.object(s, 'app_processes', return_value=[process]), patch.object(s.window_status, 'window_pids', side_effect=[{123}, set(), None]):
            self.assertEqual(s.open_profiles(self.config, root, windows_only=True), {'personal'})
            self.assertEqual(s.open_profiles(self.config, root, windows_only=True), set())
            self.assertTrue(self.config['_window_status_available'])
            self.assertEqual(s.open_profiles(self.config, root, windows_only=True), set())
            self.assertFalse(self.config['_window_status_available'])
            self.assertEqual(s.open_profiles(self.config, root), {'personal'})
        with patch.object(menu, 'green') as green, contextlib.redirect_stdout(io.StringIO()) as out:
            menu.show(self.config, set())
        green.assert_not_called()
        self.assertIn('Window status unavailable', out.getvalue())

    def test_refresh_back_multiple_selections_and_quit(self):
        opened = Mock()
        refresh = Mock(return_value={'personal'})
        with patch('builtins.input', side_effect=['r', '1', 'b', '1', 'q']), patch.object(menu, 'clear_screen') as clear, contextlib.redirect_stdout(io.StringIO()) as out:
            menu.choose(self.config, refresh, Mock(), opened)
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(refresh.call_count, 5)
        self.assertEqual(clear.call_count, 10)
        self.assertIn('r. Refresh', out.getvalue())
        self.assertIn('b. Back', out.getvalue())
        self.assertIn('q. Quit', out.getvalue())
        self.assertNotIn('Cancel', out.getvalue())

    def test_back_and_quit_during_enrollment(self):
        for error, inputs, refresh_count in [(menu.BackRequested(), ['a', 'q'], 2), (menu.QuitRequested(), ['a'], 1)]:
            refresh = Mock(return_value=set())
            with patch('builtins.input', side_effect=inputs), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(menu.choose(self.config, refresh, Mock(side_effect=error), Mock()))
            self.assertEqual(refresh.call_count, refresh_count)

    def test_action_error_keeps_picker_running(self):
        with patch('builtins.input', side_effect=['1', 'q']), contextlib.redirect_stdout(io.StringIO()) as out:
            menu.choose(self.config, Mock(return_value=set()), Mock(), Mock(side_effect=ValueError('Cannot open')))
        self.assertIn('Cannot open', out.getvalue())

    def test_ctrl_c_at_picker_quits_without_refreshing(self):
        refresh = Mock(return_value=set())
        with patch('builtins.input', side_effect=KeyboardInterrupt()), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(menu.choose(self.config, refresh, Mock(), Mock()))
        refresh.assert_called_once_with()

    def test_ctrl_c_during_actions_quits_without_refreshing(self):
        for choice, callback in [('a', 'enroll'), ('1', 'open'), ('e', 'edit'), ('d', 'docker')]:
            with self.subTest(choice=choice):
                refresh = Mock(return_value=set())
                enroll = Mock(side_effect=KeyboardInterrupt() if callback == 'enroll' else None)
                opened = Mock(side_effect=KeyboardInterrupt() if callback == 'open' else None)
                inputs = [choice, KeyboardInterrupt()]
                with patch('builtins.input', side_effect=inputs), patch.object(menu.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()):
                    self.assertIsNone(menu.choose(self.config, refresh, enroll, opened, Mock()))
                refresh.assert_called_once_with()

    def test_ctrl_c_during_refresh_quits(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(menu.choose(self.config, Mock(side_effect=KeyboardInterrupt()), Mock(), Mock()))

    def test_edit_selects_account_sanitizes_label_and_can_remove_it(self):
        for label, expected in [('Personal\n\033', 'Personal'), ('', '')]:
            with self.subTest(label=label):
                save_label, opened = Mock(), Mock()
                with patch('builtins.input', side_effect=['e', '99', '1', label, 'q']), contextlib.redirect_stdout(io.StringIO()):
                    menu.choose(self.config, Mock(return_value=set()), Mock(), opened, save_label)
                save_label.assert_called_once_with('personal', expected)
                opened.assert_not_called()

    def test_edit_back_and_quit_do_not_save(self):
        for inputs, count in [(['e', 'b', 'q'], 2), (['e', 'q'], 1)]:
            save_label, refresh = Mock(), Mock(return_value=set())
            with patch('builtins.input', side_effect=inputs), contextlib.redirect_stdout(io.StringIO()):
                menu.choose(self.config, refresh, Mock(), Mock(), save_label)
            save_label.assert_not_called()
            self.assertEqual(refresh.call_count, count)

    def test_docker_status_refresh_back_and_quit(self):
        for inputs, count, refresh_count in [(['d', 'r', 'b', 'q'], 2, 2), (['d', 'q'], 1, 1)]:
            refresh = Mock(return_value=set())
            with patch.object(menu.sys, 'platform', 'linux'), patch.object(menu.subprocess, 'run', return_value=Mock(returncode=3)) as run, patch('builtins.input', side_effect=inputs), contextlib.redirect_stdout(io.StringIO()) as out:
                menu.choose(self.config, refresh, Mock(), Mock())
            self.assertEqual(run.call_count, count)
            run.assert_called_with(['systemctl', '--user', '--no-pager', 'status', 'docker'], check=False)
            self.assertEqual(refresh.call_count, refresh_count)
            self.assertIn('Docker Status', out.getvalue())
            self.assertIn('systemctl --user --no-pager status docker', out.getvalue())
            self.assertNotIn('sudo', out.getvalue())
            self.assertIn('exited with code 3', out.getvalue())

    def test_docker_unavailable_and_unsupported_allow_back(self):
        for platform in ['linux', 'win32']:
            with patch.object(menu.sys, 'platform', platform), patch.object(menu.subprocess, 'run', side_effect=FileNotFoundError('systemctl unavailable')) as run, patch('builtins.input', side_effect=['b']), contextlib.redirect_stdout(io.StringIO()) as out:
                menu.docker_status()
            if platform == 'linux':
                self.assertIn('systemctl unavailable', out.getvalue())
            else:
                run.assert_not_called()
                self.assertIn('requires Linux', out.getvalue())

    def test_interactive_terminal_clears_screen(self):
        with patch.object(menu.os, 'name', 'posix'), patch.object(menu.sys.stdout, 'isatty', return_value=True), patch.dict(menu.os.environ, {'TERM': 'xterm'}), patch('builtins.print') as printed:
            menu.clear_screen()
        printed.assert_called_once_with('\033[2J\033[H', end='', flush=True)
