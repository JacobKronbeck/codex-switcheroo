import os
import subprocess
import unittest
from unittest.mock import Mock, patch
import window_status as windows


class WindowStatusTests(unittest.TestCase):
    def test_wayland_detects_xwayland_windows_without_wmctrl(self):
        with patch.object(windows.sys, 'platform', 'linux'), patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland'}, clear=True), patch.object(windows.shutil, 'which', side_effect=lambda name: '/usr/bin/xprop' if name == 'xprop' else None), patch.object(windows.subprocess, 'run', side_effect=[Mock(returncode=0, stdout='_NET_CLIENT_LIST(WINDOW): window id # 0x123\n'), Mock(returncode=0, stdout='_NET_WM_PID(CARDINAL) = 123\n'), Mock(returncode=0, stdout='_NET_CLIENT_LIST(WINDOW): window id #\n')]):
            self.assertEqual(windows.window_pids(), {123})
            self.assertEqual(windows.window_pids(), set())

    def test_x11_windows_refresh_and_close(self):
        with patch.object(windows.sys, 'platform', 'linux'), patch.dict(os.environ, {'XDG_SESSION_TYPE': 'x11'}, clear=True), patch.object(windows.shutil, 'which', return_value='/usr/bin/wmctrl'), patch.object(windows.subprocess, 'run', side_effect=[Mock(returncode=0, stdout='0x1 0 123 host app\n0x2 0 456 host other\n'), Mock(returncode=0, stdout='')]):
            self.assertEqual(windows.window_pids(), {123, 456})
            self.assertEqual(windows.window_pids(), set())

    def test_failed_window_query_is_unknown(self):
        for outcome in (Mock(returncode=1), OSError('unavailable'), subprocess.TimeoutExpired('wmctrl', 5)):
            with patch.object(windows.sys, 'platform', 'linux'), patch.dict(os.environ, {}, clear=True), patch.object(windows.shutil, 'which', return_value='/usr/bin/wmctrl'), patch.object(windows.subprocess, 'run', side_effect=[outcome]), patch.object(windows, 'xprop_window_pids', return_value=None):
                self.assertIsNone(windows.window_pids())

    def test_window_closed_during_query_is_ignored(self):
        with patch.object(windows.shutil, 'which', return_value='/usr/bin/xprop'), patch.object(windows.subprocess, 'run', side_effect=[Mock(returncode=0, stdout='_NET_CLIENT_LIST(WINDOW): window id # 0x123\n'), Mock(returncode=1, stdout='')]):
            self.assertEqual(windows.xprop_window_pids(), set())

    def test_missing_window_list_is_unknown(self):
        with patch.object(windows.shutil, 'which', return_value='/usr/bin/xprop'), patch.object(windows.subprocess, 'run', return_value=Mock(returncode=0, stdout='_NET_CLIENT_LIST: no such atom\n')):
            self.assertIsNone(windows.xprop_window_pids())
