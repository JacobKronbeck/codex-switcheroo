"""Read allowlisted account metadata through Codex's local app-server protocol.

Credentials remain owned by Codex. Never read auth.json, decode tokens, or log
raw protocol responses. This is local cached-session information, not a remote
validation of subscription entitlements.
"""
import json
import contextlib
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


class IdentityUnavailable(Exception):
    pass


def discover(config):
    if config.get('codex'):
        path = Path(config['codex']).expanduser()
        if path.is_file():
            return str(path)
        raise IdentityUnavailable('Configured Codex executable is unavailable.')
    app = Path(config['app']).resolve()
    for directory in (app.parent, app.parent.parent):
        for name in ('codex.exe', 'codex'):
            path = directory / 'resources' / name
            if path.is_file():
                return str(path)
    executable = shutil.which('codex')
    if executable:
        return executable
    raise IdentityUnavailable('Codex account reader unavailable; run init with --codex PATH or install Codex CLI.')


def normalize(result):
    account = result.get('account')
    if account is None:
        return {'source': 'app-server', 'status': 'signed-out'}
    if not isinstance(account, dict):
        raise IdentityUnavailable('Unsupported account response.')
    kind = account.get('type')
    if kind != 'chatgpt':
        return {'source': 'app-server', 'status': 'other-auth', 'type': kind if kind in {'apiKey', 'amazonBedrock'} else 'other'}
    # Explicit allowlist: even if a future server returns tokens, discard them.
    metadata = {'source': 'app-server', 'status': 'signed-in', 'type': 'chatgpt'}
    for key, output in [('email', 'email'), ('planType', 'plan')]:
        value = account.get(key)
        if isinstance(value, str):
            metadata[output] = ''.join(c for c in value if c.isprintable())[:160]
    routing = result.get('workspaceRouting')
    workspace = routing.get('chatgptAccountId') if isinstance(routing, dict) else None
    if isinstance(workspace, str) and 0 < len(workspace) <= 160 and workspace.isprintable():
        metadata['workspace_id'] = workspace
    return metadata


class Session:
    """One bounded stdio helper; retains notifications arriving before replies."""
    def __init__(self, executable, env, timeout):
        self.check_cancel = None
        self.deadline = time.monotonic() + timeout
        self.messages = queue.Queue()
        self.pending = []
        self.process = subprocess.Popen(
            [executable, 'app-server', '--listen', 'stdio://', '-c', 'mcp_servers={}'],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
            cwd=env.get('CODEX_HOME') or str(Path.home()),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
        def collect():
            try:
                for line in self.process.stdout:
                    if len(line) <= 1024 * 1024:
                        try:
                            self.messages.put(json.loads(line))
                        except ValueError:
                            pass
            except (OSError, ValueError):
                pass
            finally:
                self.messages.put(None)
        self.reader = threading.Thread(target=collect, daemon=True)
        self.reader.start()

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def receive(self, predicate):
        for index, message in enumerate(self.pending):
            if predicate(message):
                return self.pending.pop(index)
        while True:
            if self.check_cancel:
                self.check_cancel()
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise IdentityUnavailable('Account operation timed out.')
            try:
                message = self.messages.get(timeout=min(remaining, 0.1) if self.check_cancel else remaining)
            except queue.Empty:
                if self.check_cancel:
                    continue
                raise IdentityUnavailable('Account operation timed out.') from None
            if message is None:
                raise IdentityUnavailable('Account helper stopped before responding.')
            if not isinstance(message, dict):
                continue
            if predicate(message):
                return message
            if len(self.pending) < 100:
                self.pending.append(message)

    def request(self, identifier, method, params=None):
        self.send({'id': identifier, 'method': method, 'params': params or {}})
        message = self.receive(lambda item: item.get('id') == identifier)
        if 'error' in message or not isinstance(message.get('result'), dict):
            raise IdentityUnavailable('Account helper rejected the request.')
        return message['result']

    def initialize(self):
        self.request(1, 'initialize', {'clientInfo': {'name': 'codex_switcheroo', 'version': '0.3.0'},
                                       'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized'})

    def close(self):
        if self.process.stdin:
            with contextlib.suppress(OSError):
                self.process.stdin.close()
        if self.process.poll() is None:
            with contextlib.suppress(OSError):
                self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()  # Only our helper, never the desktop app.
            self.process.wait(timeout=2)
        if self.process.stdout:
            self.process.stdout.close()
        self.reader.join(timeout=2)


@contextlib.contextmanager
def session(executable, env, timeout, check_cancel=None):
    helper = None
    try:
        helper = Session(executable, env, timeout)
        helper.check_cancel = check_cancel
        helper.initialize()
        yield helper
    except (OSError, ValueError) as error:
        raise IdentityUnavailable('Could not communicate with the account helper.') from error
    finally:
        if helper is not None:
            helper.close()


def read_account(executable, env, timeout=5):
    with session(executable, env, timeout) as helper:
        return normalize(helper.request(2, 'account/read', {'refreshToken': False}))


def login(executable, env, timeout=300, open_browser=None, check_cancel=None):
    import webbrowser
    from urllib.parse import urlparse
    opener = open_browser or webbrowser.open
    with session(executable, env, timeout, check_cancel) as helper:
        login_id = None
        try:
            result = helper.request(2, 'account/login/start', {'type': 'chatgpt'})
            login_id = result.get('loginId')
            url = result.get('authUrl', '')
            parsed = urlparse(url)
            if not login_id or parsed.scheme != 'https' or not parsed.hostname:
                raise IdentityUnavailable('Account helper returned an invalid login URL.')
            print('Complete sign-in in your browser. Press Ctrl+C to cancel.')
            try:
                opened = opener(url)
            except Exception:
                opened = False
            if not opened:
                print('Open this login URL in your browser: ' + url)
            completed = helper.receive(lambda item: item.get('method') == 'account/login/completed'
                                       and item.get('params', {}).get('loginId') == login_id)
            if completed.get('params', {}).get('success') is not True:
                raise IdentityUnavailable('Sign-in was cancelled or failed. Try Add account again.')
            metadata = normalize(helper.request(3, 'account/read', {'refreshToken': False}))
            if metadata['status'] != 'signed-in':
                raise IdentityUnavailable('Sign-in completed but the account could not be confirmed.')
            return metadata
        except BaseException:
            if login_id:
                with contextlib.suppress(OSError, ValueError):
                    helper.send({'id': 4, 'method': 'account/login/cancel', 'params': {'loginId': login_id}})
            raise


def remembered(previous, metadata):
    if previous.get('source') == 'app-server' and (previous.get('confirmed') or previous.get('status') == 'signed-in'):
        metadata['confirmed'] = True
        if not metadata.get('email') and previous.get('email'):
            metadata['email'] = previous['email']
        same_email = metadata.get('email', '').casefold() == previous.get('email', '').casefold()
        same_workspace = (not metadata.get('workspace_id') or not previous.get('workspace_id')
                          or metadata.get('workspace_id') == previous.get('workspace_id'))
        if same_email and same_workspace:
            for key in ('workspace_id', 'workspace_label'):
                if key == 'workspace_id' and metadata.get('status') == 'signed-in':
                    continue  # A fresh response without an ID cannot prove workspace identity.
                if previous.get(key) and not metadata.get(key):
                    metadata[key] = previous[key]
    if metadata.get('status') == 'signed-in':
        metadata['confirmed'] = True
    return metadata


def refresh(config, root, launch_spec, only=None):
    try:
        executable = discover(config)
    except IdentityUnavailable:
        for name in only or config['profiles']:
            config.setdefault('details', {})[name] = remembered(config.get('details', {}).get(name, {}), {'source': 'app-server', 'status': 'unavailable'})
        return
    for name in only or config['profiles']:
        if name != 'default' and not (root / 'profiles' / name / 'codex').is_dir():
            metadata = {'source': 'app-server', 'status': 'signed-out'}
        else:
            _, env = launch_spec(config, root, name)
            try:
                metadata = read_account(executable, env)
            except IdentityUnavailable:
                previous = config.get('details', {}).get(name, {})
                # Keep only earlier automatic metadata, explicitly marked stale.
                metadata = {key: previous[key] for key in ('source', 'status', 'type', 'email', 'plan', 'workspace_id', 'workspace_label') if key in previous} if previous.get('source') == 'app-server' else {}
                metadata.update(source='app-server', status='unavailable')
        config.setdefault('details', {})[name] = remembered(config.get('details', {}).get(name, {}), metadata)
