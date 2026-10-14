"""Terminal presentation using user-entered account labels, never credentials."""
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
        username = clean(detail.get('username', '')) or 'Username not set'
        if name == active:
            username = green(username)
        marker = (' [was open]' if previous else ' [open]') if name == active else ''
        if not marker and name == config.get('last_opened'):
            marker = ' [last opened]'
        print(f'  {index}. {name}{marker} — {username}')
        print(f"     Email: {clean(detail.get('email', '')) or 'not set'} | Org: {clean(detail.get('org', '')) or 'not set'}")
    print('Details are your saved labels. Verify the signed-in account in the app.')


def edit(config, name, args=None):
    detail = config.setdefault('details', {}).setdefault(name, {})
    fields = [('username', 'Username / display name'), ('email', 'Account email'), ('org', 'Organization / workspace')]
    interactive = args is None or not any(getattr(args, key, None) is not None for key, _ in fields)
    for field, label in fields:
        supplied = getattr(args, field, None) if args is not None else None
        if supplied is not None:
            detail[field] = clean(supplied)
        elif interactive:
            value = input(f'{label} [{clean(detail.get(field, "not set"))}] (Enter to keep): ').strip()
            if value:
                detail[field] = clean(value)


def choose(config, root, active, save, validate):
    while True:
        print('\nChatGPT accounts')
        show(config, active, previous=True)
        print('  a. Add a different account\n  e. Edit account details\n  q. Cancel (app stays closed)')
        choice = input('Choose number, profile name, a, e, or q: ').strip()
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
            # Persist only once all prompts have completed.
            edit(config, name)
            config['profiles'].append(name)
            save(root, config)
            print('Sign in with the new account email when this profile opens.')
            return name
        if choice.lower() == 'e':
            name = input('Profile name to edit: ').strip()
            if name not in config['profiles']:
                print('Unknown profile.')
                continue
            edit(config, name)
            save(root, config)
            continue
        if choice in config['profiles']:
            return choice
        if choice.isdigit() and 1 <= int(choice) <= len(config['profiles']):
            return config['profiles'][int(choice) - 1]
        print('Enter a listed number, profile name, a, e, or q.')
