#!/usr/bin/env python3
"""Bind native Darwin Bun execution to the same-run macOS engine archive."""
import argparse
import json
from pathlib import Path
if __package__:
    from . import consumer_identity as identity, compare_fork_ci
else:
    import consumer_identity as identity
    import compare_fork_ci

LANE = identity.DARWIN_LANE


def evidence(proof, binaries, source, engine):
    identity.require(engine['lane'] == LANE, 'Darwin qualification requires the native macOS AOT lane')
    consumer = json.loads((proof / 'candidate-identity.json').read_text())
    identity.validate_evidence(consumer, source, engine, binaries, proof, lane=LANE)
    selected = compare_fork_ci.selection(compare_fork_ci.read_json(identity.INPUTS / 'darwin-selected.json'))
    identity.require(len(selected) == 53, 'Darwin trusted selection drift')
    observed = compare_fork_ci.validate_arm(proof / 'candidate', selected, lane=LANE)
    identity.require(observed['all_passed'], 'native Darwin selected tests failed')
    return {'passed': True, 'source': source, 'lane': LANE,
            'candidate_identity_sha256': identity.sha(proof / 'candidate-identity.json'),
            'selected_files': len(selected), 'result_files': len(observed['rows']),
            'invocation': observed['invocation'],
            'aot': identity.aot_evidence(proof, binaries, consumer, lane=LANE)}


def verify(proof, binaries, source, engine):
    measured = evidence(proof, binaries, source, engine)
    identity.require(json.loads((proof / 'gate.json').read_text()) == measured,
                     'native Darwin qualification gate differs from execution evidence')
    return measured


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--binaries', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    engine = identity.engine_input(args.artifacts / (LANE + '.tar.gz'),
                                   args.artifacts / (LANE + '.manifest.json'), args.source, LANE)
    identity.write_once(args.root / 'gate.json', evidence(args.root, args.binaries, args.source, engine))


if __name__ == '__main__':
    main()
