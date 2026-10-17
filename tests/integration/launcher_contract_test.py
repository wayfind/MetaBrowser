"""Protect persistent browser data from accidental build-directory cleanup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class LauncherContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='metabrowser-launcher-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[2] / 'scripts/run-mac.sh',
                        scripts / 'run-mac.sh')
        executable = self.root / 'out/macos-arm64/MetaBrowser.app/Contents/MacOS/Chromium'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        executable.chmod(0o700)

    def launch(self, profile=None, args=()):
        env = dict(os.environ)
        env.pop('METABROWSER_USER_DATA_DIR', None)
        if profile is not None:
            env['METABROWSER_USER_DATA_DIR'] = profile
        return subprocess.run(['/bin/bash', str(self.root / 'scripts/run-mac.sh'), *args],
                              env=env, capture_output=True, text=True, timeout=5)

    def test_default_uses_native_persistent_profile(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(arg.startswith('--user-data-dir') for arg in json.loads(result.stdout)))
        self.assertFalse((self.root / 'out/metabrowser-profile').exists())

    def test_absolute_custom_profile_and_url_remain_single_arguments(self):
        profile = str(self.root / 'custom profile')
        url = 'https://example.invalid/?query=two words'
        result = self.launch(profile, [url])
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout)
        self.assertIn('--user-data-dir=' + profile, args)
        self.assertEqual(args[-1], url)

    def test_relative_profile_refused_before_launch(self):
        result = self.launch('out/disposable-profile')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('absolute path', result.stderr)


if __name__ == '__main__':
    unittest.main()
