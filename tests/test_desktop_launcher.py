import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('bash') and shutil.which('timeout') and shutil.which('git'),
                     'Linux launcher tools required')
class DesktopLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / 'remote.git'
        self.author = root / 'author'
        self.checkout = root / 'checkout'
        self.env = dict(os.environ, GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.test',
                        GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.test',
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git(root, 'init', '--bare', str(self.remote))
        self.git(root, 'init', str(self.author))
        shutil.copy(Path(__file__).resolve().parents[1] / 'desktop-launch.sh', self.author)
        (self.author / 'requirements.txt').write_text('')
        (self.author / 'switcheroo.sh').write_text('#!/bin/bash\nprintf "PICKER:%s\\n" "$*"\n')
        (self.author / 'version').write_text('one')
        self.git(self.author, 'add', '.')
        self.git(self.author, 'commit', '-m', 'Initial')
        self.git(self.author, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.author, 'push', '-u', 'origin', 'HEAD')
        self.git(root, 'clone', str(self.remote), str(self.checkout))

    def git(self, cwd, *arguments):
        return subprocess.run(['git', *arguments], cwd=cwd, env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def publish_update(self):
        (self.author / 'version').write_text('two')
        self.git(self.author, 'commit', '-am', 'Update')
        self.git(self.author, 'push')

    def launch(self):
        result = subprocess.run(['bash', 'desktop-launch.sh', 'switch', '--skip-updates'],
                                cwd=self.checkout, env=self.env, capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PICKER:switch --skip-updates', result.stdout)
        return result

    def test_clean_checkout_pulls_update(self):
        self.publish_update()
        self.launch()
        self.assertEqual((self.checkout / 'version').read_text(), 'two')

    def test_local_edits_are_preserved_but_fetch_still_runs(self):
        self.publish_update()
        (self.checkout / 'version').write_text('local edit')
        self.assertIn('Local changes exist', self.launch().stderr)
        self.assertEqual((self.checkout / 'version').read_text(), 'local edit')
        self.assertEqual(self.git(self.checkout, 'show', 'origin/HEAD:version'), 'two')

    def test_diverged_history_is_preserved(self):
        self.publish_update()
        (self.checkout / 'version').write_text('local commit')
        self.git(self.checkout, 'commit', '-am', 'Local')
        head = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.assertIn('ahead or diverged', self.launch().stderr)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), head)

    def test_failed_fetch_still_opens_picker(self):
        self.git(self.checkout, 'remote', 'set-url', 'origin', str(self.remote / 'missing'))
        self.assertIn('update check failed', self.launch().stderr)

    def test_untracked_files_prevent_pull(self):
        self.publish_update()
        (self.checkout / 'notes').write_text('keep me')
        self.assertIn('Local changes exist', self.launch().stderr)
        self.assertEqual((self.checkout / 'version').read_text(), 'one')
