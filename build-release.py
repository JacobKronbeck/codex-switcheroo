#!/usr/bin/env python3
"""Build source distributions from an explicit list, excluding runtime state."""
import hashlib
from pathlib import Path
import shutil
import tempfile


ROOT = Path(__file__).resolve().parent
COMMON = ('README.md', 'LICENSE', 'requirements.txt', 'switcheroo.py',
          'account_identity.py', 'account_menu.py', 'window_status.py', 'VERSION')
PLATFORMS = {
    'linux': ('gztar', ('switcheroo.sh', 'desktop-launch.sh', 'install-desktop.py', 'setup-linux.sh')),
    'windows': ('zip', ('switcheroo.ps1', 'install-desktop.ps1', 'setup-windows.ps1')),
}


def build(output):
    version = (ROOT / 'VERSION').read_text().strip()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    with tempfile.TemporaryDirectory() as temporary:
        for platform, (archive_format, files) in PLATFORMS.items():
            name = f'codex-switcheroo-v{version}-{platform}'
            stage = Path(temporary) / name
            stage.mkdir()
            for file in COMMON + files:
                shutil.copy2(ROOT / file, stage / file)
            shutil.copytree(ROOT / 'docs', stage / 'docs', ignore=shutil.ignore_patterns('__pycache__'))
            archives.append(Path(shutil.make_archive(str(output / name), archive_format,
                                                    temporary, name)))
    checksums = ''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
                        for path in archives)
    (output / 'SHA256SUMS').write_text(checksums)
    return archives


if __name__ == '__main__':
    for archive in build(ROOT / 'dist'):
        print(archive)
