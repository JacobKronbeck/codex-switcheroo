"""Terminal presentation using automatically captured account metadata, never credentials."""
import os
import sys


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


def show(config, active=None, previous=False):
    for index, name in enumerate(config['profiles'], 1):
        detail = config.get('details', {}).get(name, {})
        if detail.get('source') != 'app-server':
            detail = {}
        status = detail.get('status', 'pending')
        email = clean(detail.get('email', ''))
        account = email or {'signed-in': 'ChatGPT account (email unavailable)', 'signed-out': 'Not signed in yet', 'other-auth': 'Non-ChatGPT authentication', 'unavailable': 'Account details unavailable'}.get(status, 'Waiting for first sign-in')
        if name == active and status == 'signed-in' and email:
            account = green(account)
        marker = (' [was open]' if previous else ' [open]') if name == active else ''
        if not marker and name == config.get('last_opened'):
            marker = ' [last opened]'
        print(f'  {index}. {name}{marker} — {account}')
        plan = clean(detail.get('plan', '')) or 'not available'
        print(f'     Plan: {plan} | Organization: not provided by app')
        if status == 'unavailable' and email:
            print('     Cached details — could not refresh this account')
    print('Account details come from the local session. Email identifies the account.')


def choose(config, root, active, save, validate):
    while True:
        print('\nChatGPT accounts')
        show(config, active, previous=True)
        print('  a. Add a different account\n  q. Cancel (app stays closed)')
        choice = input('Choose number, profile name, a, or q: ').strip()
        if choice.lower() == 'q':
            return None
        if choice.lower() == 'a':
            try:
                name = validate(input('New profile name (e.g. second-account): ').strip())
            except ValueError as error:
                print(error)
                continue
            if name in config['profiles']:
                print('That profile already exists. Select it to sign in.')
                continue
            config['profiles'].append(name)
            save(root, config)
            print('Sign in with the new account email when this profile opens.')
            return name
        if choice in config['profiles']:
            return choice
        if choice.isdigit() and 1 <= int(choice) <= len(config['profiles']):
            return config['profiles'][int(choice) - 1]
        print('Enter a listed number, profile name, a, or q.')
