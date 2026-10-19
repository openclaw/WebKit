import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import artifacts


class SourceHistory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update({
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_SYSTEM': os.devnull, 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_AUTHOR_NAME': 'Fixture', 'GIT_COMMITTER_NAME': 'Fixture',
            'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
            'GIT_AUTHOR_DATE': '2026-01-01T00:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-01-01T00:00:00+00:00',
        })

    def git(self, repository, *args, data=None):
        return subprocess.check_output(
            ['git', '-c', 'commit.gpgsign=false', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
                '-C', str(repository), *args],
            input=data, env=self.env, stderr=subprocess.PIPE)

    def capture(self, repository, *args, data=None):
        return self.git(repository, *args, data=data).decode().strip()

    def graph(self, name, bypass=False):
        repository = self.root / name
        repository.mkdir()
        self.git(repository, 'init', '--quiet', '--object-format=sha1')
        commits = {}
        edges = [('X', []), ('F', ['X']), ('B', ['F']), ('H', ['B', 'X'])] if bypass else [
            ('A0', []), ('A1', ['A0']), ('A2', ['A1']), ('A3', ['A2']), ('A4', ['A3']),
            ('F', ['A4']), ('S', ['F']), ('P', ['S']), ('V1', ['S']), ('V2', ['V1']),
            ('V3', ['V2']), ('B', ['F', 'V3']), ('H', ['P', 'B']),
        ]
        docker = self.capture(repository, 'hash-object', '-w', '--stdin', data=b'FROM scratch\n')
        for subject, parents in edges:
            payload = self.capture(repository, 'hash-object', '-w', '--stdin', data=(subject + '\n').encode())
            tree = self.capture(repository, 'mktree', data=(
                f'100644 blob {docker}\tDockerfile\n100644 blob {payload}\tpayload.txt\n').encode())
            parent_args = [item for parent in parents for item in ['-p', commits[parent]]]
            commits[subject] = self.capture(repository, 'commit-tree', tree, *parent_args, data=(subject + '\n').encode())
        self.git(repository, 'update-ref', 'refs/heads/candidate', commits['H'])
        self.git(repository, 'symbolic-ref', 'HEAD', 'refs/heads/candidate')
        self.git(repository, 'reset', '--hard', commits['H'])
        return repository, commits

    def clone(self, repository, depth):
        destination = self.root / (repository.name + '-depth-' + str(depth))
        self.git(self.root, 'clone', '--single-branch', '--branch', 'candidate', '--depth', str(depth),
            repository.as_uri(), str(destination))
        return destination

    def source(self, repository, base, floor):
        with patch.dict(os.environ, self.env, clear=True), patch.multiple(
            artifacts, ROOT=repository, BASE=base, HISTORY_FLOOR=floor, RECIPE=['Dockerfile']):
            return artifacts.source()

    def oracle(self, repository, commits, names):
        return {'source': commits['H'], 'base': commits['B'], 'history_floor': commits['F'], 'patches': [
            {'commit': commits[name], 'subject': name, 'patch_sha256': hashlib.sha256(
                self.git(repository, 'show', '--format=', '--binary', commits[name])).hexdigest()}
            for name in names]}

    def rejects_before_lane(self, repository, base, floor, error=ValueError):
        destination = self.root / 'forbidden-output'
        with patch.dict(os.environ, self.env, clear=True), patch.multiple(
            artifacts, ROOT=repository, BASE=base, HISTORY_FLOOR=floor, RECIPE=['Dockerfile']), patch.object(
            artifacts, 'lane_definitions', side_effect=AssertionError('lane execution reached')) as lanes:
            with self.assertRaises(error):
                artifacts.preflight()
            with self.assertRaises(error):
                artifacts.build('bun-webkit-linux-amd64', destination)
            lanes.assert_not_called()
        self.assertFalse(destination.exists())

    def test_complete_history_and_raw_patch_hashes(self):
        repository, commits = self.graph('complete')
        self.assertEqual(self.source(repository, commits['B'], commits['F']),
            self.oracle(repository, commits, ['P', 'H']))

    def test_boundary_on_excluded_parent_rejects_before_execution(self):
        repository, commits = self.graph('excluded-parent')
        expected = self.oracle(repository, commits, ['P', 'H'])
        shallow = self.clone(repository, 4)
        self.git(shallow, 'merge-base', '--is-ancestor', commits['F'], commits['B'])
        with self.assertRaisesRegex(ValueError, 'shallow boundary above history floor'):
            self.source(shallow, commits['B'], commits['F'])
        self.rejects_before_lane(shallow, commits['B'], commits['F'])
        self.git(shallow, 'fetch', '--deepen=16', 'origin', 'candidate')
        self.assertEqual(self.source(shallow, commits['B'], commits['F']), expected)

    def test_boundary_below_floor_preserves_complete_record(self):
        repository, commits = self.graph('below-floor')
        shallow = self.clone(repository, 7)
        self.assertEqual(self.capture(shallow, 'rev-parse', '--is-shallow-repository'), 'true')
        self.assertEqual(self.source(shallow, commits['B'], commits['F']),
            self.oracle(repository, commits, ['P', 'H']))

    def test_bypass_parent_rejects_when_old_boundary_guard_passes(self):
        repository, commits = self.graph('bypass', bypass=True)
        expected = self.oracle(repository, commits, ['H'])
        self.assertEqual(self.source(repository, commits['B'], commits['F']), expected)
        shallow = self.clone(repository, 3)
        shallow_path = Path(self.capture(shallow, 'rev-parse', '--git-path', 'shallow'))
        if not shallow_path.is_absolute():
            shallow_path = shallow / shallow_path
        boundaries = set(shallow_path.read_text().splitlines())
        self.assertTrue(boundaries)
        above_floor = set(self.capture(shallow, 'rev-list', commits['F'] + '..' + commits['H']).splitlines())
        self.assertFalse(boundaries.intersection(above_floor))
        with self.assertRaisesRegex(ValueError, 'patch commit is not a proven history-floor descendant'):
            self.source(shallow, commits['B'], commits['F'])
        self.rejects_before_lane(shallow, commits['B'], commits['F'])
        self.git(shallow, 'fetch', '--deepen=16', 'origin', 'candidate')
        self.assertEqual(self.source(shallow, commits['B'], commits['F']), expected)

    def test_missing_base_or_floor_stops_before_execution(self):
        repository, commits = self.graph('missing')
        for base, floor in [('0' * 40, commits['F']), (commits['B'], '0' * 40)]:
            with self.subTest(base=base, floor=floor):
                with self.assertRaises(subprocess.CalledProcessError):
                    self.source(repository, base, floor)
                self.rejects_before_lane(repository, base, floor, subprocess.CalledProcessError)


if __name__ == '__main__':
    unittest.main()
