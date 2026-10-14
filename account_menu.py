"""Terminal picker for automatically confirmed accounts."""
import os
import sys
import contextlib
import io
import subprocess
import re


def clean(value):
    return ''.join(c for c in str(value) if c.isprintable()).strip()[:160]


def green(value):
    return _color(value, 32)


def blue(value, bold=False):
    return _color(value, '1;34' if bold else 34)


def _color(value, code):
    if not sys.stdout.isatty() or 'NO_COLOR' in os.environ or os.environ.get('TERM') == 'dumb':
        return value
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return value
        if not ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 4):
            return value
    return f'\033[{code}m' + value + '\033[0m'


def accounts(config):
    details = config.get('details', {})
    return [name for name in config['profiles']
            if details.get(name, {}).get('source') == 'app-server'
            and (details[name].get('confirmed') or details[name].get('status') == 'signed-in')]


def show(config, active=None):
    active = {active} if isinstance(active, str) else set(active or ())
    names = accounts(config)
    if not names:
        print('  No accounts\n  Add an account to get started.')
    for index, name in enumerate(names, 1):
        detail = config['details'][name]
        email = clean(detail.get('email', '')) or 'ChatGPT account (email unavailable)'
        peers = [peer for peer in names if config['details'][peer].get('email', '').casefold()
                 == detail.get('email', '').casefold()]
        workspace = clean(detail.get('workspace_label', ''))
        if workspace:
            email += ' — ' + workspace
        if len(peers) > 1 and (not workspace or sum(
                clean(config['details'][peer].get('workspace_label', '')).casefold() == workspace.casefold()
                for peer in peers) > 1):
            email += f' — Workspace {peers.index(name) + 1}'
        status = detail.get('status')
        if name in active and status == 'signed-in':
            label = green('● ' + email)
            if label == '● ' + email:
                label += ' [open]'
        else:
            label = email
            if status != 'signed-in':
                label += ' — ' + {'signed-out': 'Sign-in required', 'other-auth': 'Sign-in required',
                                  'unavailable': 'Status unavailable'}.get(status, 'Status unavailable')
        print(f'  {index}. {label}')
    if names and config.get('_window_status_available') is False:
        print('\n  Window status unavailable on this desktop.')
    return names


class BackRequested(Exception):
    pass


class QuitRequested(Exception):
    pass


def clear_screen():
    if sys.stdout.isatty() and os.environ.get('TERM') != 'dumb':
        if os.name == 'nt':
            os.system('cls')
        else:
            print('\033[2J\033[H', end='', flush=True)


def login_navigation():
    """Poll console input while the helper owns browser callback processing."""
    if not sys.stdin.isatty():
        return
    if os.name == 'nt':
        import msvcrt
        if not msvcrt.kbhit():
            return
        key = msvcrt.getwch().lower()
    else:
        import select
        readable, _, _ = select.select([sys.stdin], [], [], 0)
        if not readable:
            return
        key = sys.stdin.readline().strip().lower()
    if key == 'b':
        raise BackRequested()
    if key in {'q', '\x03'}:
        raise QuitRequested()


def edit_label(config, save_label):
    clear_screen()
    print('Edit account label\n')
    names = show(config)
    if not names:
        return 'No accounts to edit.'
    while True:
        choice = input('\nChoose account number, b to go back, or q to quit: ').strip().lower()
        if choice == 'b':
            return ''
        if choice == 'q':
            raise QuitRequested()
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            selected = names[int(choice) - 1]
            break
        print('Enter a listed account number, b, or q.')
    current = clean(config['details'][selected].get('workspace_label', ''))
    print('\nCurrent label: ' + (current or '(none)'))
    label = clean(input('New label (blank removes the label): '))
    save_label(selected, label)
    return 'Account label saved.'


def docker_status():
    while True:
        clear_screen()
        print('Docker Status\n', flush=True)
        if sys.platform != 'linux':
            print('Docker service status requires Linux with systemctl.')
        else:
            print('Containers (current Docker context; includes stopped containers)\n', flush=True)
            try:
                result = subprocess.run(
                    ['docker', 'ps', '--all', '--format',
                     'table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'],
                    capture_output=True, text=True, timeout=10, check=False)
                if result.returncode:
                    print('Could not list containers: ' + (clean(result.stderr)
                          or f'Docker exited with code {result.returncode}.'))
                else:
                    # Preserve table spacing while stripping terminal control characters.
                    lines = result.stdout.splitlines()
                    if len(lines) <= 1:
                        print('No containers found in the current Docker context.')
                    else:
                        for line in lines:
                            print(''.join(char for char in line if char.isprintable() or char == '\t'))
                        print('\nSTATUS includes uptime, health (when configured), or exit details.')
            except subprocess.TimeoutExpired:
                print('Docker container query timed out after 10 seconds.')
            except OSError as error:
                print('Could not list containers: ' + clean(error))

            print('\nRootless user service\n\nsystemctl --user --no-pager status docker\n', flush=True)
            try:
                result = subprocess.run(['systemctl', '--user', '--no-pager', 'status', 'docker'], check=False)
                if result.returncode:
                    print(f'\nStatus command exited with code {result.returncode}.')
            except OSError as error:
                print('Could not read Docker status: ' + clean(error))
        print('\n  r. Refresh\n  b. Back\n  q. Quit')
        while True:
            choice = input('\nChoose r, b, or q: ').strip().lower()
            if choice == 'q':
                raise QuitRequested()
            if choice == 'b':
                return
            if choice == 'r':
                break
            print('Enter r, b, or q.')


def help_page():
    clear_screen()
    rows = [
        ('#', 'Open or activate account #'),
        ('q#', 'Quit account # window (e.g. q2)'),
        ('q*', 'Quit all account windows'),
        ('remove #', 'Remove account # from the list; keeps local data and windows'),
        ('a', 'Add account'),
        ('e', 'Edit account label'),
        ('d', 'Show Docker status'),
        ('r', 'Refresh accounts'),
        ('h', 'Show help'),
        ('b', 'Back'),
        ('q / Ctrl+C', 'Quit picker; account windows stay open'),
    ]
    headers = ('Command', 'Description')
    widths = [max(len(row[index]) for row in [headers, *rows]) for index in range(2)]
    border = '  +' + '+'.join('-' * (width + 2) for width in widths) + '+'

    def print_row(row):
        print('  | ' + ' | '.join(value.ljust(width) for value, width in zip(row, widths)) + ' |')

    print('Help\n')
    print(border)
    print_row(headers)
    print(border)
    for row in rows:
        print_row(row)
    print(border + '\n')
    while True:
        choice = input('b to go back, q to quit: ').strip().lower()
        if choice == 'b':
            return
        if choice == 'q':
            raise QuitRequested()


def choose(config, refresh, enroll, open_account, save_label=None, close_account=None, remove_account=None):
    try:
        return _choose(config, refresh, enroll, open_account, save_label, close_account, remove_account)
    except (KeyboardInterrupt, QuitRequested):
        print()
        return None


def _choose(config, refresh, enroll, open_account, save_label, close_account, remove_account):
    notice = ''
    while True:
        clear_screen()
        print('ChatGPT accounts — refreshing…', flush=True)
        try:
            active = refresh()
        except (OSError, ValueError) as error:
            active = set()
            notice = 'Could not refresh: ' + clean(error)
        clear_screen()
        print('ChatGPT accounts\n')
        names = show(config, active)
        print('\n  a. Add account\n  e. Edit account label\n  d. Docker Status\n  r. Refresh\n  h. Help\n  b. Back\n  q. Quit')
        if notice:
            print('\n' + notice)
        choice = input('\nChoose account number or command (h for help): ').strip().lower()
        notice = ''
        if choice == 'q':
            return None
        if choice in {'r', 'b'}:
            continue
        selected = None
        try:
            action = re.fullmatch(r'(q)\s*([0-9]+)|remove\s+([0-9]+)', choice)
            if choice == 'q*':
                notice = close_account('*') if close_account else 'Command unavailable.'
            elif action:
                number = int(action[2] or action[3])
                if not 1 <= number <= len(names):
                    notice = 'Enter a listed account number. Type h for help.'
                else:
                    callback = close_account if action[1] else remove_account
                    if callback is None:
                        notice = 'Command unavailable.'
                    else:
                        notice = callback(names[number - 1])
            elif choice == 'h':
                help_page()
            elif choice == 'a':
                clear_screen()
                print('Add account\n  b. Back   q. Quit (press Enter after the key)\n')
                selected = enroll()
                if selected is None:
                    notice = 'Account was not added. You can try again.'
            elif choice == 'e':
                if save_label is None:
                    notice = 'Label editing is unavailable.'
                else:
                    notice = edit_label(config, save_label)
            elif choice == 'd':
                docker_status()
            elif choice.isdigit() and 1 <= int(choice) <= len(names):
                selected = names[int(choice) - 1]
            else:
                notice = 'Enter a listed account number or command. Type h for help.'
            if selected is not None:
                print('\nOpening account — waiting for its window…', flush=True)
                # Preserve one action message in the next screen, not a scrolling log.
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    open_account(selected)
                lines = output.getvalue().strip().splitlines()
                notice = lines[-1] if lines else 'Account selected.'
        except QuitRequested:
            return None
        except BackRequested:
            notice = 'Returned to accounts.'
        except (OSError, ValueError) as error:
            notice = clean(error)
