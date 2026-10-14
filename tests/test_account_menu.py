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
    def setUp(self):
        self.config = {'app': '/fake/app', 'profiles': ['default', 'personal'], 'details': {'personal': {'username': 'Example User', 'email': 'user@example.test', 'org': 'Personal'}}}

    def test_menu_shows_details_and_accepts_name(self):
        with patch('builtins.input', return_value='personal'), contextlib.redirect_stdout(io.StringIO()) as out:
            result = menu.choose(self.config, Path('/fake'), None, Mock(), s.valid_name)
        self.assertEqual(result, 'personal')
        for value in ('Example User', 'user@example.test', 'Personal', 'Add a different account'):
            self.assertIn(value, out.getvalue())

    def test_add_from_menu_saves_then_selects(self):
        save = Mock()
        with patch('builtins.input', side_effect=['a', 'second-account', 'Second User', 'second@example.test', 'Other org']), contextlib.redirect_stdout(io.StringIO()):
            name = menu.choose(self.config, Path('/fake'), None, save, s.valid_name)
        self.assertEqual(name, 'second-account')
        self.assertIn(name, self.config['profiles'])
        self.assertEqual(self.config['details'][name]['email'], 'second@example.test')
        save.assert_called_once()

    def test_invalid_add_stays_in_menu(self):
        with patch('builtins.input', side_effect=['a', '../escape', 'q']), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(menu.choose(self.config, Path('/fake'), None, Mock(), s.valid_name))

    def test_cancelled_enrollment_does_not_save(self):
        save = Mock()
        with patch('builtins.input', side_effect=['a', 'second-account', KeyboardInterrupt]), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            menu.choose(self.config, Path('/fake'), None, save, s.valid_name)
        save.assert_not_called()
        self.assertNotIn('second-account', self.config['profiles'])

    def test_terminal_controls_are_removed(self):
        self.assertEqual(menu.clean('Name\n\033\t'), 'Name')

    def test_color_only_for_tty_and_respects_no_color(self):
        with patch.object(menu.os, 'name', 'posix'), patch.object(menu.sys.stdout, 'isatty', return_value=True), patch.dict(menu.os.environ, {'TERM': 'xterm'}, clear=True):
            self.assertEqual(menu.green('User'), '\033[32mUser\033[0m')
            with patch.dict(menu.os.environ, {'NO_COLOR': '1'}):
                self.assertEqual(menu.green('User'), 'User')
        with patch.object(menu.sys.stdout, 'isatty', return_value=False):
            self.assertEqual(menu.green('User'), 'User')

    def test_last_opened_is_not_green_or_claimed_logged_in(self):
        self.config['last_opened'] = 'personal'
        with patch.object(menu, 'green') as green, contextlib.redirect_stdout(io.StringIO()) as out:
            menu.show(self.config)
        green.assert_not_called()
        self.assertIn('[last opened]', out.getvalue())
        self.assertNotIn('[open]', out.getvalue())

    def test_only_open_profile_username_is_green(self):
        with patch.object(menu, 'green', side_effect=lambda v: '<green>' + v) as green, contextlib.redirect_stdout(io.StringIO()) as out:
            menu.show(self.config, 'personal', previous=True)
        green.assert_called_once_with('Example User')
        self.assertIn('[was open]', out.getvalue())

    def test_active_profile_recognizes_managed_path(self):
        root = Path('/fake').resolve()
        process = Mock()
        process.cmdline.return_value = ['/fake/app', '--user-data-dir=' + str(root / 'profiles/personal/desktop')]
        with patch.object(s, 'app_processes', return_value=[process]):
            self.assertEqual(s.active_profile(self.config, root), 'personal')

    def test_multiple_open_profiles_are_not_guessed(self):
        root = Path('/fake').resolve()
        first, second = Mock(), Mock()
        first.cmdline.return_value = ['/fake/app']
        second.cmdline.return_value = ['/fake/app', '--user-data-dir=' + str(root / 'profiles/personal/desktop')]
        with patch.object(s, 'app_processes', return_value=[first, second]):
            self.assertIsNone(s.active_profile(self.config, root))

    def test_old_config_without_details_still_renders(self):
        self.config.pop('details')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            menu.show(self.config)
        self.assertIn('Username not set', out.getvalue())


if __name__ == '__main__':
    unittest.main()
