import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class ReleasePackageTests(unittest.TestCase):
    def test_platform_packages_have_launchers_and_valid_checksums_without_state(self):
        spec = importlib.util.spec_from_file_location('build_release', ROOT / 'build-release.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            archives = builder.build(output)
            self.assertEqual(len(archives), 2)
            for archive in archives:
                if archive.suffix == '.zip':
                    with zipfile.ZipFile(archive) as package:
                        names = package.namelist()
                    required = {'setup-windows.ps1', 'install-desktop.ps1', 'switcheroo.ps1'}
                else:
                    with tarfile.open(archive) as package:
                        names = package.getnames()
                    required = {'setup-linux.sh', 'install-desktop.py', 'switcheroo.sh', 'desktop-launch.sh'}
                files = {Path(name).name for name in names}
                self.assertTrue(required <= files)
                self.assertTrue({'VERSION', 'switcheroo.py', 'requirements.txt', 'LICENSE'} <= files)
                self.assertFalse({'auth.json', 'config.json', '.env', '.git', '.venv', 'profiles'} & files)
                self.assertIn(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name,
                              (output / 'SHA256SUMS').read_text())


@unittest.skipUnless(os.name != 'nt' and shutil.which('bash'), 'Linux setup requires bash')
class LinuxSetupTests(unittest.TestCase):
    def run_setup(self, arguments=(), answer='', initialized=False, fail_pip=False):
        with tempfile.TemporaryDirectory(prefix='switcheroo setup ') as temporary:
            root = Path(temporary)
            shutil.copy(ROOT / 'setup-linux.sh', root)
            shutil.copy(ROOT / 'switcheroo.sh', root)
            binary = root / 'bin'
            binary.mkdir()
            (binary / 'python3').write_text('#!/bin/bash\nexit 0\n')
            (binary / 'python3').chmod(0o755)
            venv = root / '.venv' / 'bin'
            venv.mkdir(parents=True)
            python = venv / 'python'
            python.write_text('''#!/bin/bash
if [[ "$1" == -c ]]; then exit "$FAKE_INITIALIZED"; fi
if [[ "$1" == -m ]]; then exit "$FAKE_PIP_STATUS"; fi
printf 'INVOKED:%s\\n' "$*"
''')
            python.chmod(0o755)
            env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                       FAKE_INITIALIZED='0' if initialized else '1',
                       FAKE_PIP_STATUS='1' if fail_pip else '0')
            return subprocess.run(['bash', str(root / 'setup-linux.sh'), *arguments],
                                  input=answer, capture_output=True, text=True, env=env, timeout=10)

    def test_default_skips_icon_and_initializes(self):
        result = self.run_setup(answer='\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('switcheroo.py init', result.stdout)
        self.assertNotIn('INVOKED:install-desktop.py', result.stdout)

    def test_icon_can_be_selected_interactively_or_by_flag(self):
        for arguments, answer in [((), 'y\n'), (('--desktop-icon',), '')]:
            result = self.run_setup(arguments, answer)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('INVOKED:install-desktop.py', result.stdout)

    def test_existing_configuration_is_kept_and_explicit_skip_does_not_prompt(self):
        result = self.run_setup(('--no-desktop-icon',), initialized=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('switcheroo.py init', result.stdout)
        self.assertNotIn('INVOKED:install-desktop.py', result.stdout)

    def test_dependency_failure_stops_before_init_or_shortcut(self):
        result = self.run_setup(('--desktop-icon',), fail_pip=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('INVOKED:', result.stdout)

    def test_unknown_option_is_rejected(self):
        self.assertEqual(self.run_setup(('--unknown',)).returncode, 2)
