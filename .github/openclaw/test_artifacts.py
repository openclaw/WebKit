import copy
import hashlib
import json
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


class ArtifactHeaders(unittest.TestCase):
    def test_lane_abi_defaults_and_consumer_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'include').mkdir()
            for aot in (0, 1):
                with self.subTest(aot=aot):
                    (root / 'include/cmakeconfig.h').write_text('/* generated config */\n')
                    artifacts.write_build_defines(root, {
                        'aot': aot, 'defines': 'BUN_HARDENED=1 ENABLE_AOT_GUARDED_PAGES=1',
                    }, 'a' * 40)
                    consumer = ('#include "cmakeconfig.h"\n'
                        '#if !defined(ENABLE_AOT)\n#define ENABLE_AOT 1\n#endif\n'
                        '#if BUN_WEBKIT_ENABLE_AOT != ' + str(aot) + '\n#error library ABI mismatch\n#endif\n'
                        '#if ENABLE_AOT != EXPECTED_AOT || BUN_HARDENED != EXPECTED_HARDENED || ENABLE_AOT_GUARDED_PAGES != 1\n'
                        '#error consumer ABI mismatch\n#endif\n')
                    command = ['cc', '-E', '-x', 'c', '-I' + str(root / 'include'), '-']
                    for overrides in [
                        ['-DEXPECTED_AOT=' + str(aot), '-DEXPECTED_HARDENED=1'],
                        ['-DENABLE_AOT=' + str(1 - aot), '-DEXPECTED_AOT=' + str(1 - aot),
                         '-DBUN_HARDENED=0', '-DEXPECTED_HARDENED=0'],
                    ]:
                        subprocess.run(command + overrides, input=consumer, text=True, capture_output=True, check=True)


class PreflightAdmission(unittest.TestCase):
    def test_sync_branch_is_qualification_only(self):
        cases = [
            ('refs/heads/claude/sync-webkit-upstream-20261014', 'false', True),
            ('refs/heads/claude/sync-webkit-upstream-20261014', 'true', False),
            ('refs/heads/claude/sync-webkit-upstream-20261014', None, False),
            ('refs/heads/unrelated', 'false', False),
            ('refs/heads/openclaw/main', 'true', True),
            ('refs/heads/openclaw/batch-1', 'false', True),
            ('refs/heads/openclaw/release-5718a6ec', 'true', True),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for ref, publish, allowed in cases:
                with self.subTest(ref=ref, publish=publish):
                    output = Path(temporary) / 'output'
                    output.unlink(missing_ok=True)
                    env = {'GITHUB_REF': ref, 'INPUT_SHA': 'a' * 40,
                        'GITHUB_SHA': 'a' * 40, 'GITHUB_OUTPUT': str(output)}
                    if publish is not None:
                        env['INPUT_PUBLISH'] = publish
                    with patch.dict(os.environ, env, clear=True), patch.object(
                        artifacts, 'source', return_value={'source': 'a' * 40}), patch.object(
                        artifacts, 'CONFIG', {'lanes': [{'label': 'fixture'}]}), patch.object(
                        artifacts, 'lane_definitions', return_value=[{'label': 'fixture'}]) as lanes:
                        if allowed:
                            artifacts.preflight()
                            self.assertIn('fixture', output.read_text())
                            lanes.assert_called_once()
                        else:
                            with self.assertRaisesRegex(ValueError, 'permitted owned branch'):
                                artifacts.preflight()
                            lanes.assert_not_called()
                            self.assertFalse(output.exists())


    def test_consumer_carrier_requires_exact_engine_and_frozen_matrix(self):
        engine = '42e4245f4180941634b482a7e8ef7fca47467de5'
        original = copy.deepcopy(artifacts.CONFIG)
        original['candidate'] = {'commit': 'b' * 40, 'tree': 'c' * 40, 'manifest_blob': 'd' * 40}
        cases = [
            ('false', engine, None, None),
            ('true', engine, None, 'permitted owned branch'),
            (None, engine, None, 'permitted owned branch'),
            ('false', 'e' * 40, None, 'engine source mismatch'),
            ('false', engine, 'baseline', 'matrix/configuration drift'),
            ('false', engine, 'lanes', 'matrix/configuration drift'),
            ('false', engine, 'candidate', 'matrix/configuration drift'),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for publish, source, drift, error in cases:
                with self.subTest(publish=publish, engine=source, drift=drift):
                    output = Path(temporary) / 'output'
                    output.unlink(missing_ok=True)
                    config = copy.deepcopy(artifacts.CONFIG)
                    if drift == 'baseline':
                        config['baseline']['commit'] = 'f' * 40
                    elif drift == 'lanes':
                        config['lanes'][0]['consumer'] = 'changed consumer'
                    elif drift == 'candidate':
                        config['candidate']['commit'] = 'f' * 40
                    env = {'GITHUB_REF': 'refs/heads/claude/hosted-linux-consumer-20261031',
                        'INPUT_SHA': 'a' * 40, 'GITHUB_SHA': 'a' * 40,
                        'ENGINE_SHA': source, 'GITHUB_OUTPUT': str(output)}
                    if publish is not None:
                        env['INPUT_PUBLISH'] = publish
                    with patch.dict(os.environ, env, clear=True), patch.object(
                        artifacts, 'source', return_value={'source': 'a' * 40}), patch.object(
                        artifacts, 'CONFIG', config), patch.object(
                        artifacts, 'capture', return_value=json.dumps(original)), patch.object(
                        artifacts, 'run') as ancestry, patch.object(
                        artifacts, 'lane_definitions', return_value=config['lanes']) as lanes:
                        if error:
                            with self.assertRaisesRegex(ValueError, error):
                                artifacts.preflight()
                            lanes.assert_not_called()
                            self.assertFalse(output.exists())
                        else:
                            artifacts.preflight()
                            matrix = json.loads(output.read_text().split('=', 1)[1])
                            self.assertEqual(matrix['include'], [{'lane': lane['label']} for lane in config['lanes']])
                            ancestry.assert_called_once_with('git', '-C', str(artifacts.ROOT),
                                'merge-base', '--is-ancestor', engine, 'a' * 40)

    def test_consumer_carrier_rejects_unrelated_history_before_lane_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'output'
            env = {'GITHUB_REF': 'refs/heads/claude/hosted-linux-consumer-20261031',
                'INPUT_SHA': 'a' * 40, 'GITHUB_SHA': 'a' * 40, 'INPUT_PUBLISH': 'false',
                'ENGINE_SHA': '42e4245f4180941634b482a7e8ef7fca47467de5', 'GITHUB_OUTPUT': str(output)}
            with patch.dict(os.environ, env, clear=True), patch.object(
                artifacts, 'source', return_value={'source': 'a' * 40}), patch.object(
                artifacts, 'run', side_effect=subprocess.CalledProcessError(1, ['git'])), patch.object(
                artifacts, 'lane_definitions') as lanes:
                with self.assertRaises(subprocess.CalledProcessError):
                    artifacts.preflight()
                lanes.assert_not_called()
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
