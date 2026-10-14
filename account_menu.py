"""Terminal picker for automatically confirmed accounts."""
import os
import sys
import contextlib
import io


def clean(value):
    return ''.join(c for c in str(value) if c.isprintable()).strip()[:160]


def green(value):
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
    return '\033[32m' + value + '\033[0m'


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
    if key == 'q':
        raise QuitRequested()


def choose(config, refresh, enroll, open_account):
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
        print('\n  a. Add account\n  r. Refresh\n  b. Back\n  q. Quit')
        if notice:
            print('\n' + notice)
        try:
            choice = input('\nChoose account number, a, r, b, or q: ').strip().lower()
        except KeyboardInterrupt:
            notice = 'Use q to quit.'
            continue
        notice = ''
        if choice == 'q':
            return None
        if choice in {'r', 'b'}:
            continue
        selected = None
        try:
            if choice == 'a':
                clear_screen()
                print('Add account\n  b. Back   q. Quit (press Enter after the key)\n')
                selected = enroll()
                if selected is None:
                    notice = 'Account was not added. You can try again.'
            elif choice.isdigit() and 1 <= int(choice) <= len(names):
                selected = names[int(choice) - 1]
            else:
                notice = 'Enter a listed account number, a, r, b, or q.'
            if selected is not None:
                # Preserve one action message in the next screen, not a scrolling log.
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    open_account(selected)
                lines = output.getvalue().strip().splitlines()
                notice = lines[-1] if lines else 'Account selected.'
        except QuitRequested:
            return None
        except (BackRequested, KeyboardInterrupt):
            notice = 'Returned to accounts.'
        except (OSError, ValueError) as error:
            notice = clean(error)
