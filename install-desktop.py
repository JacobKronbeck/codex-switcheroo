#!/usr/bin/env python3
"""Install a terminal launcher in the Linux app menu and Desktop folder."""
import os
from pathlib import Path
import shutil
import subprocess


def exec_quote(value):
    # Desktop Entry Exec uses its own quoting, followed by string escaping.
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value.replace('\\', '\\\\') + '"'


def main():
    project = Path(__file__).resolve().parent
    data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    applications = data_home / 'applications'
    desktop = Path.home() / 'Desktop'
    if shutil.which('xdg-user-dir'):
        result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            desktop = Path(result.stdout.strip())
    content = (
        '[Desktop Entry]\n'
        'Type=Application\n'
        'Name=Codex Switcheroo\n'
        'Comment=Update from GitHub and open the account picker\n'
        f'Exec=bash {exec_quote(project / "desktop-launch.sh")}\n'
        'Icon=system-users\n'
        'Terminal=true\n'
        'Categories=Utility;\n'
    )
    destinations = [applications / 'codex-switcheroo.desktop']
    if desktop != Path.home():
        destinations.append(desktop / 'codex-switcheroo.desktop')
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        destination.chmod(0o755)
        if shutil.which('gio'):
            subprocess.run(['gio', 'set', str(destination), 'metadata::trusted', 'true'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f'Installed: {destination}')


if __name__ == '__main__':
    main()
