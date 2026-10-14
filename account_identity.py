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
    return metadata


def read_account(executable, env, timeout=5):
    process = None
    messages = queue.Queue()
    try:
        process = subprocess.Popen(
            [executable, 'app-server', '--listen', 'stdio://', '-c', 'mcp_servers={}'],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
            cwd=env.get('CODEX_HOME') or str(Path.home()),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)

        def collect():
            try:
                for line in process.stdout:
                    if len(line) > 1024 * 1024:
                        continue
                    try:
                        messages.put(json.loads(line))
                    except ValueError:
                        continue
            except (OSError, ValueError):
                pass
            finally:
                messages.put(None)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout

        def send(message):
            process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()

        def response(identifier):
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IdentityUnavailable('Account reader timed out.')
                try:
                    message = messages.get(timeout=remaining)
                except queue.Empty:
                    raise IdentityUnavailable('Account reader timed out.') from None
                if message is None:
                    raise IdentityUnavailable('Account reader stopped before responding.')
                if isinstance(message, dict) and message.get('id') == identifier:
                    if 'error' in message:
                        raise IdentityUnavailable('Account reader rejected the metadata request.')
                    result = message.get('result')
                    if not isinstance(result, dict):
                        raise IdentityUnavailable('Invalid account reader response.')
                    return result

        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'codex_switcheroo', 'version': '0.2.0'}}})
        response(1)
        send({'method': 'initialized'})
        send({'id': 2, 'method': 'account/read', 'params': {'refreshToken': False}})
        return normalize(response(2))
    except (OSError, ValueError) as error:
        raise IdentityUnavailable('Could not read account metadata through Codex.') from error
    finally:
        if process is not None:
            if process.stdin:
                with contextlib.suppress(OSError):
                    process.stdin.close()
            if process.poll() is None:
                with contextlib.suppress(OSError):
                    process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()  # Only our short-lived metadata helper, never the app.
                process.wait(timeout=2)
            if process.stdout:
                with contextlib.suppress(OSError):
                    process.stdout.close()


def refresh(config, root, launch_spec, only=None):
    try:
        executable = discover(config)
    except IdentityUnavailable:
        for name in only or config['profiles']:
            config.setdefault('details', {})[name] = {'source': 'app-server', 'status': 'unavailable'}
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
                metadata = {key: previous[key] for key in ('source', 'status', 'type', 'email', 'plan') if key in previous} if previous.get('source') == 'app-server' else {}
                metadata.update(source='app-server', status='unavailable')
        config.setdefault('details', {})[name] = metadata
