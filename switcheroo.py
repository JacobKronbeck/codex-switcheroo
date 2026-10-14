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
import account_menu
import account_identity


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
        json.dump(config, handle, indent=2)
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
    expected = os.path.normcase(str(Path(executable).resolve()))
    matches = []
    for process in psutil.process_iter(['pid', 'exe']):
        try:
            path = process.info['exe']
            if path and os.path.normcase(str(Path(path).resolve())) == expected:
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


def active_profile(config, root):
    """Identify an open profile from launch arguments without inspecting auth."""
    import psutil
    candidates = set()
    for process in app_processes(config['app']):
        try:
            args = process.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if any(arg.startswith('--type=') for arg in args):
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
    return next(iter(candidates)) if len(candidates) == 1 else None


def choose_profile(config, root, active=None):
    return account_menu.choose(config, root, active, save_config, valid_name)


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
                if profile not in config['profiles'] or config.get('last_opened') != profile:
                    return
            # Probe outside the lock so sign-in and other commands remain usable.
            account_identity.refresh(config, root, launch_spec, only=[profile])
            metadata = config['details'][profile]
            if metadata.get('status') == 'signed-in':
                with locked(root):
                    current = json.loads((root / 'config.json').read_text(encoding='utf-8'))
                    if profile not in current['profiles'] or current.get('last_opened') != profile:
                        return
                    current.setdefault('details', {})[profile] = metadata
                    save_config(root, current)
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(5)


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) == 2 and arguments[0] == '_watch':
        watch_identity(state_root(), arguments[1])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action')
    init = sub.add_parser('init', help='Discover app and create local configuration')
    init.add_argument('--app', help='Path to ChatGPT executable')
    init.add_argument('--codex', help='Optional Codex CLI executable for automatic account details')
    add = sub.add_parser('add', help='Register an empty account profile; switch to it to sign in once')
    add.add_argument('name')
    sub.add_parser('list', help='Show account details and currently open profile')
    sub.add_parser('doctor', help='Print paths and executable status, without opening profile data')
    switch = sub.add_parser('switch', help='Close, check updates, select and open')
    switch.add_argument('profile', nargs='?')
    switch.add_argument('--skip-updates', action='store_true')
    switch.add_argument('--install-updates', action='store_true')
    switch.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(arguments or ['switch'])
    root = state_root()
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
            print('Initialized. default opens your existing app account. Use add NAME for another account.')
            return
        if not path.exists():
            raise SwitchError('Run init first.')
        config = json.loads(path.read_text(encoding='utf-8'))
        profiles = config['profiles']
        if args.action == 'add':
            name = valid_name(args.name)
            if name in profiles:
                raise SwitchError('Profile already exists.')
            profiles.append(name)
            save_config(root, config)
            print(f'Added {name}. Run switch {name} and sign into this profile once.')
        elif args.action == 'list':
            account_identity.refresh(config, root, launch_spec)
            save_config(root, config)
            account_menu.show(config, active_profile(config, root))
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
                print(f'Would close {config["app"]}, check updates, select {args.profile or "interactively"}, and launch with isolated profile paths.')
                return
            # Check support before closing the app; update errors leave the menu usable.
            if not args.skip_updates:
                update_command(args.install_updates)
            active = active_profile(config, root)
            close_app(config['app'])
            if not args.skip_updates:
                check_updates(args.install_updates)
            account_identity.refresh(config, root, launch_spec)
            save_config(root, config)
            selected = args.profile or choose_profile(config, root, active)
            if selected is None:
                return
            command, env = launch_spec(config, root, selected)
            try:
                subprocess.Popen(command, env=env, start_new_session=(os.name != 'nt'), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                raise SwitchError('Could not launch the app. Run doctor and check the configured executable.') from exc
            config['last_opened'] = selected
            save_config(root, config)
            start_identity_watch(selected)
            print(f'Opened profile {selected}. Sign in if requested; account details are captured automatically.')
        else:
            parser.print_help()


if __name__ == '__main__':
    try:
        main()
    except (SwitchError, OSError, ValueError, KeyError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled. If already closed, ChatGPT remains closed.', file=sys.stderr)
        sys.exit(130)
