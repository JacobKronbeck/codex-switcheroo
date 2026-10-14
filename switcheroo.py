#!/usr/bin/env python3
"""Local ChatGPT desktop profile launcher. Never reads or exports credentials."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import account_menu
import account_identity
import window_status


class SwitchError(ValueError):
    pass


def state_root():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'codex-switcheroo'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'codex-switcheroo'


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        path.chmod(0o700)


@contextlib.contextmanager
def locked(root):
    private_dir(root)
    # OS locks release after a crash; never remove a lock another process owns.
    with (root / 'switch.lock').open('a+b') as handle:
        handle.seek(0)
        handle.write(b'0')
        handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SwitchError('Another switcheroo command is running.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def save_config(root, config):
    temporary = root / 'config.tmp'
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump({key: value for key, value in config.items()
                   if key != '_window_status_available'}, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    if os.name != 'nt':
        temporary.chmod(0o600)
    temporary.replace(root / 'config.json')


def discover_app():
    found = shutil.which('chatgpt')
    if found:
        return str(Path(found).resolve())
    if sys.platform == 'win32':
        script = "Get-AppxPackage | Where-Object {$_.Name -match 'ChatGPT|Codex'} | ForEach-Object { $p = $_.InstallLocation; Get-ChildItem -LiteralPath $p -Recurse -File -ErrorAction SilentlyContinue | Where-Object {$_.Name -in @('ChatGPT.exe','Codex.exe')} | Select-Object -ExpandProperty FullName }"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
        candidates = list(dict.fromkeys(p.strip() for p in result.stdout.splitlines() if p.strip()))
        if len(candidates) == 1:
            return candidates[0]
    raise SwitchError('Cannot identify one ChatGPT executable. Use init --app PATH_TO_EXECUTABLE.')


def valid_name(name):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', name) or name in {'con', 'prn', 'aux', 'nul'} or re.fullmatch(r'(com|lpt)[0-9]', name):
        raise SwitchError('Use 1–40 lowercase letters, digits or hyphens; start with a letter. Reserved Windows names are unavailable.')
    return name


def launch_spec(config, root, profile):
    env = os.environ.copy()
    # Default means the original app, even when this terminal inherited a custom home.
    for key in ('CODEX_ELECTRON_USER_DATA_PATH', 'CODEX_HOME',
                'CODEX_SQLITE_HOME', 'CODEX_ACCESS_TOKEN', 'OPENAI_API_KEY'):
        env.pop(key, None)
    command = [config['app']]
    if profile != 'default':
        base = root / 'profiles' / valid_name(profile)
        desktop = base / 'desktop'
        codex = base / 'codex'
        for directory in (base, desktop, codex):
            private_dir(directory)
        env['CODEX_ELECTRON_USER_DATA_PATH'] = str(desktop)
        env['CODEX_HOME'] = str(codex)
        command.append('--user-data-dir=' + str(desktop))
    return command, env


def app_processes(executable):
    import psutil
    path = Path(executable).resolve()
    expected = {os.path.normcase(str(path))}
    # Fedora's command is a shell wrapper which execs the sibling desktop binary.
    if path.name == 'codex-launcher' and (path.parent / 'ChatGPT').is_file():
        expected.add(os.path.normcase(str((path.parent / 'ChatGPT').resolve())))
    matches = []
    for process in psutil.process_iter(['pid', 'exe']):
        try:
            path = process.info['exe']
            if path and os.path.normcase(str(Path(path).resolve())) in expected:
                matches.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return matches


def close_app(executable):
    import psutil
    processes = app_processes(executable)
    if not processes:
        return
    print('Closing ChatGPT. Finish running tasks before using this command.')
    if sys.platform == 'win32':
        # Ask windows to close rather than forcibly terminating the process tree.
        ids = ','.join(str(p.pid) for p in processes)
        script = f'Get-Process -Id {ids} -ErrorAction SilentlyContinue | ForEach-Object {{[void]$_.CloseMainWindow()}}'
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], check=True)
    else:
        for process in processes:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
    deadline = time.monotonic() + 20
    while app_processes(executable):
        if time.monotonic() >= deadline:
            raise SwitchError('ChatGPT is still running. Quit it manually and retry; no forced kill was used.')
        time.sleep(0.25)


def update_command(install=False):
    if sys.platform == 'win32':
        if not shutil.which('winget'):
            raise SwitchError('winget is missing; check Microsoft Store updates or use --skip-updates.')
        if install:
            return ['winget', 'upgrade', '--id', '9PLM9XGG6VKS', '--exact', '--source', 'msstore']
        return ['winget', 'list', '--id', '9PLM9XGG6VKS', '--exact', '--source', 'msstore', '--upgrade-available']
    if sys.platform.startswith('linux') and shutil.which('dnf'):
        return (['sudo', 'dnf', 'upgrade', '--refresh', 'chatgpt'] if install else ['dnf', 'check-upgrade', '--refresh', 'chatgpt'])
    raise SwitchError('Automatic update checks support Fedora DNF and Windows Store installations. Use --skip-updates for other installs.')


def check_updates(install=False):
    print('Installing app updates…' if install else 'Checking app updates…', flush=True)
    result = subprocess.run(update_command(install), check=False)
    allowed = {0} if install or sys.platform == 'win32' else {0, 100}
    if result.returncode not in allowed:
        print(f'Update command returned {result.returncode}; update status is unknown. Continuing with the installed app.', file=sys.stderr)


def open_profiles(config, root, *, windows_only=False):
    """Identify running profiles, optionally requiring an actual desktop window."""
    import psutil
    visible = None
    if windows_only:
        visible = window_status.window_pids()
        config['_window_status_available'] = visible is not None
        if visible is None:
            return set()
    candidates = set()
    for process in app_processes(config['app']):
        if windows_only and process.pid not in visible:
            continue
        try:
            args = process.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if any(arg.startswith('--type=') for arg in args):
            continue
        if windows_only and any(arg in {'--ozone-platform=wayland', '--ozone-platform=auto',
                                        '--ozone-platform-hint=auto'} for arg in args):
            # Native Wayland windows are absent from the XWayland window list.
            config['_window_status_available'] = False
            continue
        paths = [arg.split('=', 1)[1] for arg in args if arg.startswith('--user-data-dir=')]
        if '--user-data-dir' in args:
            index = args.index('--user-data-dir')
            if index + 1 < len(args):
                paths.append(args[index + 1])
        if not paths:
            candidates.add('default')
        else:
            for name in config['profiles']:
                if name == 'default':
                    continue
                expected = os.path.normcase(str((root / 'profiles' / name / 'desktop').resolve()))
                if any(os.path.normcase(str(Path(path).resolve())) == expected for path in paths):
                    candidates.add(name)
    return candidates


def active_profile(config, root):
    """Compatibility helper for callers expecting one profile."""
    candidates = open_profiles(config, root)
    return next(iter(candidates)) if len(candidates) == 1 else None


def refresh_accounts(config, root):
    # The original app is always a discovery candidate, even in an empty config.
    if 'default' not in config['profiles']:
        config['profiles'].insert(0, 'default')
    account_identity.refresh(config, root, launch_spec)
    save_config(root, config)
    return open_profiles(config, root, windows_only=True)


def enroll_account(config, root, name=None):
    name = valid_name(name) if name else 'account-' + uuid.uuid4().hex[:12]
    if name == 'default' or name in config['profiles'] or (root / 'profiles' / name).exists():
        raise SwitchError('Profile already exists. Select it with switch PROFILE.')
    base = root / 'profiles' / name
    registered = False
    try:
        executable = account_identity.discover(config)
        _, env = launch_spec(config, root, name)
        # Keep newly enrolled credentials scoped to this home, not a shared keyring.
        settings = base / 'codex' / 'config.toml'
        settings.write_text('cli_auth_credentials_store = "file"\n', encoding='utf-8')
        if os.name != 'nt':
            settings.chmod(0o600)
        metadata = account_identity.login(executable, env, check_cancel=account_menu.login_navigation)
        metadata['confirmed'] = True
        email = metadata.get('email', '').casefold()
        for existing in account_menu.accounts(config):
            if email and config['details'][existing].get('email', '').casefold() == email:
                print('That account is already saved. Using the existing account.')
                return existing
        config['profiles'].append(name)
        config.setdefault('details', {})[name] = metadata
        save_config(root, config)
        registered = True
        print('Account added: ' + (metadata.get('email') or 'ChatGPT account'))
        return name
    except (account_identity.IdentityUnavailable, KeyboardInterrupt, OSError) as error:
        if not registered and name in config['profiles']:
            config['profiles'].remove(name)
            config.get('details', {}).pop(name, None)
        print('Sign-in cancelled.' if isinstance(error, KeyboardInterrupt) else str(error))
        return None
    finally:
        if name not in config['profiles'] and base.exists():
            shutil.rmtree(base)  # Only the new, unregistered enrollment directory.


def choose_profile(config, root, active=None):
    def reload_config():
        current = json.loads((root / 'config.json').read_text(encoding='utf-8'))
        config.clear()
        config.update(current)

    def refresh():
        with locked(root):
            reload_config()
            return refresh_accounts(config, root)

    def enroll():
        with locked(root):
            reload_config()
            return enroll_account(config, root)

    def open_selected(selected):
        with locked(root):
            reload_config()
            if selected not in config['profiles']:
                raise SwitchError('Account no longer exists. Refresh and select again.')
            return open_account(config, root, selected)

    return account_menu.choose(config, refresh, enroll, open_selected)


def activate_profile(config, root, profile):
    """Try OS window activation; a running process may have no visible window."""
    import psutil
    pids = []
    for process in app_processes(config['app']):
        try:
            args = process.cmdline()
            if any(arg.startswith('--type=') for arg in args):
                continue
            # Reuse the same profile identification logic on this one process.
            paths = [arg.split('=', 1)[1] for arg in args if arg.startswith('--user-data-dir=')]
            if '--user-data-dir' in args:
                index = args.index('--user-data-dir')
                paths += args[index + 1:index + 2]
            expected = os.path.normcase(str((root / 'profiles' / profile / 'desktop').resolve()))
            if (profile == 'default' and not paths) or (profile != 'default' and any(
                    os.path.normcase(str(Path(path).resolve())) == expected for path in paths)):
                pids.append(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    try:
        if sys.platform == 'win32' and pids:
            ids = ','.join(str(int(pid)) for pid in pids)
            script = ("Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                      "public class SwitcherooWindow { [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h); "
                      "[DllImport(\"user32.dll\")] public static extern bool ShowWindowAsync(IntPtr h, int c); }'; "
                      f"Get-Process -Id {ids} -ErrorAction SilentlyContinue | ForEach-Object {{ "
                      "if ($_.MainWindowHandle -ne 0) { [void][SwitcherooWindow]::ShowWindowAsync($_.MainWindowHandle,9); "
                      "if ([SwitcherooWindow]::SetForegroundWindow($_.MainWindowHandle)) { exit 0 } } }; exit 1")
            return subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
        if sys.platform.startswith('linux') and shutil.which('wmctrl') and pids:
            result = subprocess.run(['wmctrl', '-lp'], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                fields = line.split(None, 4)
                if len(fields) >= 3 and fields[2].isdigit() and int(fields[2]) in pids:
                    return subprocess.run(['wmctrl', '-ia', fields[0]], stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def open_account(config, root, selected):
    active = refresh_accounts(config, root)
    running = selected in active or selected in open_profiles(config, root)
    if running and activate_profile(config, root, selected):
        print('Account window activated.')
        return
    # Background processes do not prove that a window exists. Launch the same
    # profile again so the desktop's per-user-data single-instance handler can
    # restore/create its window, including on Wayland where wmctrl cannot help.
    command, env = launch_spec(config, root, selected)
    try:
        subprocess.Popen(command, env=env, start_new_session=(os.name != 'nt'),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise SwitchError('Could not launch the app. Run doctor and check the configured executable.') from exc
    config['last_opened'] = selected
    save_config(root, config)
    start_identity_watch(selected)
    email = config.get('details', {}).get(selected, {}).get('email')
    if running:
        print('Requested window reopen for ' + (email or 'this account') + '.')
    else:
        print('Opened ' + (email or 'account window') + '. Sign in if requested.')


def start_identity_watch(profile):
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_watch', profile],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=(os.name != 'nt'),
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
    except OSError:
        print('Background account capture unavailable; details will refresh next time.', file=sys.stderr)


def watch_identity(root, profile, duration=300):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        try:
            with locked(root):
                config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
                if profile not in config['profiles']:
                    return
            # Probe outside the lock so sign-in and other commands remain usable.
            account_identity.refresh(config, root, launch_spec, only=[profile])
            metadata = config['details'][profile]
            if metadata.get('status') == 'signed-in':
                with locked(root):
                    current = json.loads((root / 'config.json').read_text(encoding='utf-8'))
                    if profile not in current['profiles']:
                        return
                    current.setdefault('details', {})[profile] = metadata
                    save_config(root, current)
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(5)


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    # Switch is the default action, including when only its options are given.
    if arguments and arguments[0] in {'--skip-updates', '--install-updates', '--dry-run'}:
        arguments = ['switch', *arguments]
    if len(arguments) == 2 and arguments[0] == '_watch':
        watch_identity(state_root(), arguments[1])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action')
    init = sub.add_parser('init', help='Discover app and create local configuration')
    init.add_argument('--app', help='Path to ChatGPT executable')
    init.add_argument('--codex', help='Optional Codex CLI executable for automatic account details')
    add = sub.add_parser('add', help='Sign in through your browser and open the account')
    add.add_argument('name', nargs='?', help='Optional legacy internal profile name')
    sub.add_parser('list', help='Show account details and currently open profile')
    sub.add_parser('doctor', help='Print paths and executable status, without opening profile data')
    switch = sub.add_parser('switch', help='Select and open an account, keeping existing windows open')
    switch.add_argument('profile', nargs='?')
    switch.add_argument('--skip-updates', action='store_true')
    switch.add_argument('--install-updates', action='store_true')
    switch.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(arguments or ['switch'])
    root = state_root()
    run_picker = False
    with locked(root):
        path = root / 'config.json'
        if args.action == 'init':
            if path.exists():
                raise SwitchError('Already initialized; edit the local config.json to change the executable.')
            app = str(Path(args.app).expanduser().resolve()) if args.app else discover_app()
            if not Path(app).is_file():
                raise SwitchError('App executable does not exist.')
            config = {'app': app, 'profiles': ['default']}
            if args.codex:
                config['codex'] = str(Path(args.codex).expanduser().resolve())
            save_config(root, config)
            print('Initialized. Run switch to choose an account or add to sign in.')
            return
        if not path.exists():
            raise SwitchError('Run init first.')
        config = json.loads(path.read_text(encoding='utf-8'))
        profiles = config['profiles']
        if args.action == 'add':
            if not Path(config['app']).is_file():
                raise SwitchError('App executable moved or was removed. Run doctor.')
            refresh_accounts(config, root)
            try:
                selected = enroll_account(config, root, args.name)
            except account_menu.QuitRequested:
                return
            except account_menu.BackRequested:
                selected = None
            if selected is not None:
                open_account(config, root, selected)
            run_picker = True
        elif args.action == 'list':
            account_menu.show(config, refresh_accounts(config, root))
        elif args.action == 'doctor':
            print(f'Local state: {root}\nApp: {config["app"]}\nExecutable exists: {Path(config["app"]).is_file()}')
            try:
                print('Account reader: ' + account_identity.discover(config))
            except account_identity.IdentityUnavailable:
                print('Account reader unavailable. Install Codex CLI or set codex in this local config.')
            print('Profile isolation uses internal app settings; Windows and live sign-in still require manual validation.')
        elif args.action == 'switch':
            if args.profile and args.profile not in profiles:
                raise SwitchError('Unknown profile. Use list or add NAME.')
            if not Path(config['app']).is_file():
                raise SwitchError('App executable moved or was removed. Edit local config.json; run doctor.')
            if args.skip_updates and args.install_updates:
                raise SwitchError('--skip-updates and --install-updates cannot be combined.')
            if args.dry_run:
                print(f'Would select {args.profile or "interactively"}, refresh account/window status, '
                      'and open or activate the account with isolated profile paths. Existing windows stay open.')
                return
            if args.install_updates and app_processes(config['app']):
                raise SwitchError('Quit all account windows before installing updates. No windows were closed.')
            if not args.skip_updates:
                try:
                    check_updates(args.install_updates)
                except (SwitchError, OSError) as error:
                    if args.install_updates:
                        raise
                    print(str(error) + ' Continuing with the installed app.', file=sys.stderr)
            if args.profile is not None:
                open_account(config, root, args.profile)
            run_picker = True
        else:
            parser.print_help()
    if run_picker:
        choose_profile(config, root)


if __name__ == '__main__':
    try:
        main()
    except (SwitchError, OSError, ValueError, KeyError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled. Existing account windows remain open.', file=sys.stderr)
        sys.exit(130)
