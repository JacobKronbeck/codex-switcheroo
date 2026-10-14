"""Read desktop window ownership; None means detection is unavailable."""
import os
import re
import shutil
import subprocess
import sys


def window_pids():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        pids = set()

        @callback_type
        def collect(handle, _):
            if user32.IsWindowVisible(handle):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                if pid.value:
                    pids.add(pid.value)
            return True

        return pids if user32.EnumWindows(collect, 0) else None
    # The installed Linux desktop uses XWayland even in a Wayland session.
    # Query its actual windows, never infer them from background processes.
    if not sys.platform.startswith('linux'):
        return None
    if not shutil.which('wmctrl'):
        return xprop_window_pids()
    try:
        result = subprocess.run(['wmctrl', '-lp'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return xprop_window_pids()
    pids = set()
    for line in result.stdout.splitlines():
        fields = line.split(None, 4)
        if len(fields) >= 3 and fields[2].isdigit() and int(fields[2]) > 0:
            pids.add(int(fields[2]))
    return pids


def xprop_window_pids():
    """Read only X11/XWayland window IDs and owning PIDs (no window titles)."""
    if not shutil.which('xprop'):
        return None
    try:
        result = subprocess.run(['xprop', '-root', '_NET_CLIENT_LIST'],
                                capture_output=True, text=True, timeout=3)
        if result.returncode != 0 or not result.stdout.startswith('_NET_CLIENT_LIST(WINDOW):'):
            return None
        pids = set()
        for window in re.findall(r'0x[0-9a-fA-F]+', result.stdout):
            owner = subprocess.run(['xprop', '-id', window, '_NET_WM_PID'],
                                   capture_output=True, text=True, timeout=3)
            if owner.returncode != 0:
                continue  # A window can close between the two queries.
            match = re.search(r'^_NET_WM_PID\(CARDINAL\) = (\d+)\s*$', owner.stdout)
            if match and int(match[1]) > 0:
                pids.add(int(match[1]))
        return pids
    except (OSError, subprocess.TimeoutExpired):
        return None
