"""Admit fixed-run build artifacts and fresh Linux proof for offline assembly."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile

REPO = "repos/openclaw/WebKit/"
SOURCE = "42e4245f4180941634b482a7e8ef7fca47467de5"
BUILD_RUN = 41286392252
BUILD_HEAD = "bfea5fad536fe27d6beb39bdf64106536418428f"
REPLAY_RUN = 41294955235
REPLAY_HEAD = "fe913cc9c90efd8fdc9c9f5be06ef3450d63cab4"
ORIGINAL = {'bun-webkit-linux-amd64': [13075718771,
                            709340274,
                            'sha256:e762b6e8022b4d0f454b1ddc8288f0b3b2ad511b159fe2b8cff7fd4a4eb197d4'],
 'bun-webkit-linux-amd64-lto': [13076530203,
                                390685186,
                                'sha256:6133bb0507c93acf3d1d2231012c3ccb0bb8f077c27293f316e79a2e2f5c43ce'],
 'bun-webkit-linux-amd64-musl-lto': [13076429158,
                                     283858242,
                                     'sha256:14457d9621316dccdc6b6eceef32e7f03410a7e7db62e26e30355f90273ac601'],
 'bun-webkit-linux-arm64-lto': [13076480901,
                                269297056,
                                'sha256:d9419c90be30b7588a11e9607edca4a16b23e39f4363013e0edda11dcb409dce'],
 'bun-webkit-linux-arm64-musl-lto': [13077105948,
                                     193259412,
                                     'sha256:cdcdb82ed96e2b4b80e9059acd6e408cbd47b549a7671497f6282de37428daf4'],
 'bun-webkit-macos-amd64-lto': [13076422209,
                                184072987,
                                'sha256:17c48099e23731b46b3814d09fee6d102d79508f31b3a4bd6d5841cb84dd2da3'],
 'bun-webkit-macos-arm64': [13075372671,
                            229404673,
                            'sha256:71689535668a18cf61cc4ef8f0dae281b48108b4923ce0b2af4e5ca7a5a8e15a'],
 'bun-webkit-macos-arm64-lto': [13076322480,
                                179644957,
                                'sha256:e2f0a8e675814af177875eab7e6475e49b3eb0777ffe26b65d468944e7ebb543'],
 'bun-webkit-windows-amd64-lto': [13076798389,
                                  572218334,
                                  'sha256:aaf339963631c8b83877fa90fa11809c7e7af59066c20bd7b8e0325d72a77324'],
 'bun-webkit-windows-arm64': [13077561521,
                              259571300,
                              'sha256:09735badc7ff3faf690c16dee640ce1842c8bc62e10fc6be4819124e86c3c8de'],
 'windows-arm64-qualification': [13077641419,
                                 1029,
                                 'sha256:c263cbb260585a610e0c1670cab7530b0efe3e694c3598fde845a50e5795a1a2']}



CURRENT_SOURCE = "4430cc2e4caa5720c2f78963be3566c87b958084"
CURRENT_BUILD_RUN = 41330085617
CURRENT_REPLAY_RUN = 41367738580
CURRENT_REPLAY_HEAD = "b1b043eab568e09d22aed763db4ccdbfabdda209"
CURRENT_ARTIFACTS = {'windows-arm64-qualification': [13100526385, 1030, 'sha256:e5a1023b3eee615fd425fa9ff0240651756ed5cd49c6f306bfb1faba0bf16d81'], 'bun-webkit-linux-amd64-debug-asan-aot': [13100491403, 1502877343, 'sha256:b42b231c1f93d915fdf2a264cf98c6b5ab72ca557d43913c500b1a817db0ee84'], 'bun-webkit-windows-amd64-lto-aot': [13099053509, 1167505439, 'sha256:d035131aef9997860f5a926833a8cc901738229c714dd31f91a1ec2864d4b34e'], 'bun-webkit-windows-arm64-aot': [13098919990, 509526074, 'sha256:744e004317674127a9df90ec96bac1f91f78a671ab2c0cf73d2fafda45973bcb'], 'bun-webkit-linux-amd64-musl-lto-aot': [13098637413, 460629779, 'sha256:41b99d250cc703f3f577d5e5d87526bbe19fe1a661cabfc4f10ac5e36b616102'], 'bun-webkit-macos-amd64-lto-aot': [13098130771, 367154425, 'sha256:b4d52c5cd93a22b38440864e06a73516a190f2c959289009f0a9c4741f4a0976'], 'bun-webkit-linux-arm64-musl-lto-aot': [13097684412, 360823888, 'sha256:4276ae47b5d02c375a645de81b12cd2ce6b6f63fc30b67c97e7a8f8d10b57866'], 'bun-webkit-linux-amd64-lto-aot': [13097301126, 809941034, 'sha256:99c264399fbccb9ec29c8dbcee91f4788d6d32d870bd13b9de2398c56d1cca5d'], 'bun-webkit-macos-arm64-lto-aot': [13096634579, 365308705, 'sha256:b1d3901fa6eebf599353eb2cce8edec015de49b41eb2a0c598f1cf5f94e1e5ea'], 'bun-webkit-linux-amd64-aot': [13096122278, 1286964541, 'sha256:e2ab6664f6f7018cd482a685eb17cd85afc1398a77d994b5cd0b176a72406c88'], 'bun-webkit-linux-arm64-lto-aot': [13096089459, 673116454, 'sha256:0384ee939b0de577b9af68159b0a8cd64a72fe6847faaa5e859d265b4e41200a'], 'bun-webkit-macos-arm64-aot': [13096006955, 517796721, 'sha256:de9fdeb0bd2f01761fe3be01c2781fc8eec6880a1f63cc806c769095ff260d3a'], 'bun-webkit-windows-amd64-lto': [13095457134, 576373143, 'sha256:4ecf261352922636c098a3b1c18a155273ecc6b8f037f0e4c9a440db38e0aa23'], 'bun-webkit-linux-arm64-musl-lto': [13095256139, 195528802, 'sha256:cc3848bdf9d59d827beaf0beb8d0aadd0d24b9aec8e659da430b8b52c439203e'], 'bun-webkit-linux-amd64-musl-lto': [13095145789, 286895594, 'sha256:7e81bf573529f208ed825f7263d963f53f10e85120ddaf93acb5d43b50dd42cc'], 'bun-webkit-macos-amd64-lto': [13094590399, 186203947, 'sha256:cee63035ac330f8194b20890981427836862cb7642a60719bd02f3bfefdb370d'], 'bun-webkit-windows-arm64': [13094578632, 262415745, 'sha256:416c7002cd2785cfa56264adf95f284d1bbb39f7ae325b8dc1a5a4f37c9d41bd'], 'bun-webkit-linux-arm64-lto': [13093674197, 270916785, 'sha256:9a79d225e19e82926b8b4b85dbfdf3af1e0efae4725fbb767af37cc6b5b38f59'], 'bun-webkit-linux-amd64': [13093547315, 716162784, 'sha256:cf8da5e9e6b7dda9733ef9479e116df621470b3fa02cafd88f1711aa5e4734be'], 'bun-webkit-linux-amd64-lto': [13093273208, 392276872, 'sha256:baeac1a0d61b75c09c55d35d4d0a1ec4deefc37e2694cc2fb42d8fb7130f1f52'], 'bun-webkit-macos-arm64': [13093236334, 231948605, 'sha256:16e9962e7d58dbe747fc6e3fb07f87f8d377d91a427fecd59705add37c521042'], 'bun-webkit-macos-arm64-lto': [13093064757, 181681295, 'sha256:1eb059504f5c0efa9888f0b85137722ce165dcedba352c775d24a8fb603922c8']}
CURRENT_REUSED_FILES = {'accounting-baseline.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'accounting-concurrent.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'accounting-dfg.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'accounting-ftl.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'accounting-interpreter.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'baseline-adapters.patch': 'f71aad14e31d2dbd84178827362721fd486aeb0f11764cd9b39c9353af171e5a', 'baseline-build-tools.json': '5da6181f23deee8cedb8e9a3d53e64351bbe050d56fcf4d6939c983e80bfb0d6', 'baseline-identity.json': '1be4f57cb699a7465b4dd30e3d697b3e727d905773fd5a93664064a63d69b1f8', 'build-baseline.log': 'ff09be1932d5f4de6f3fc301067443e380b36ec2742d4e19d83f3337db2e3615', 'bun-baseline.sha256': 'd1084bf9aafaa4dfec1e8ccb488c5cd2e7433ee35cc15b7332f97ad7320f1163', 'engine-gate.json': '962f28f87c91a0b7a9008f9272ee84b6f52f8886fa834ed9f188f525f56ef099', 'jsc-context.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-modules/results': 'f8642f15db9d5374d7573d84d8ff14a7054b52cdd6617cf7c90e0984eb4a67b8', 'jsc-modules.log': 'ec8b45a9e3c9e2f28c86dbcca4393cb9bf37f43d185b2992dbf4ae998634c24d', 'jsc-stack/baseline-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/baseline-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/baseline-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/baseline-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-files.json': '73440853a5503fe67fa54c9197f8a0f02bbb87c6a3ea2024e170e8d7783365eb', 'jsc-stack/cache-owned-cold-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-owned-cold-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-owned-cold-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-owned-cold-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-owned-warm-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-owned-warm-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-owned-warm-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-owned-warm-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-cold-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-cold-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-cold-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-cold-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-warm-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-warm-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-warm-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/cache-persistent-warm-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/concurrent-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/concurrent-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/concurrent-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/concurrent-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/default-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/default-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/default-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/default-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/dfg-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/dfg-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/dfg-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/dfg-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/eager-ftl-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/eager-ftl-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/eager-ftl-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/eager-ftl-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/interpreter-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/interpreter-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/interpreter-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/interpreter-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/optimizer-callsite-async-position.mjs.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/optimizer-callsite-syntax-positions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/optimizer-stack-position-regressions-cache.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stack/optimizer-stack-position-regressions.js.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'jsc-stress/results': 'b873a5f035cd72211c72b2f5ffe4419cd93e1c014e4ec52b570e53bb151fcdea', 'jsc-stress.log': '5a20f58f45d1e0c304a7a51c56e2d25f668c0992fb81537047ed961b53210750', 'sampling-baseline.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'sampling-default.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'sampling-ftl.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'sampling-interpreter.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'stack-visitor.log': 'd306d58b17e3fd865b753d29b76016c20d079ef3f1bd0a7684f97106e2fcb3b3', 'vm-test-baseline.sha256': '55a16d8f7dc191c830c6520b90eeee02af36cee97dc58b3ae972a96e9dd559d6'}
CURRENT_CONTROLLER_SHA256 = '662568bfe12cea4a5d723720a36a5d659b5e4bc07196fe1d9b21cea8ebc775f5'


def api(route):
    return json.loads(subprocess.check_output(["gh", "api", REPO + route]))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def run_identity(run_id, head, workflow):
    run = api(f"actions/runs/{run_id}")
    assert run["head_sha"] == head and run["run_attempt"] == 1 and run["status"] == "completed"
    assert run["head_repository"]["full_name"] == "openclaw/WebKit"
    assert run["path"].split("@", 1)[0] == ".github/workflows/" + workflow
    jobs = api(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100")["jobs"]
    return run, {job["name"]: job for job in jobs}


def download(root, label, row, run_id, head, *, max_archive_bytes=1024**3):
    artifact_id, size, digest = row
    assert 0 < max_archive_bytes <= 2 * 1024**3
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest) and 0 < size <= max_archive_bytes
    metadata = api(f"actions/artifacts/{artifact_id}")
    assert metadata["id"] == artifact_id and metadata["name"] == label and not metadata["expired"]
    assert metadata["size_in_bytes"] == size and metadata["digest"] == digest
    assert metadata["workflow_run"]["id"] == run_id and metadata["workflow_run"]["head_sha"] == head
    archive_path = root / "download.zip"
    with archive_path.open("xb") as stream:
        subprocess.run(["gh", "api", REPO + f"actions/artifacts/{artifact_id}/zip"], stdout=stream, check=True)
    assert archive_path.stat().st_size == size and "sha256:" + sha(archive_path) == digest
    target = root / label
    target.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        assert 0 < len(entries) <= 4096 and sum(entry.file_size for entry in entries) <= 8 * 1024**3
        seen = set()
        for entry in entries:
            name = PurePosixPath(entry.filename)
            assert not name.is_absolute() and not any(part in ("", ".", "..") for part in entry.filename.rstrip("/").split("/"))
            assert "\\" not in entry.filename and "\x00" not in entry.filename and name not in seen
            seen.add(name)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if entry.is_dir():
                assert mode in (0, stat.S_IFDIR) and entry.file_size == 0
                (target / name).mkdir(parents=True, exist_ok=True)
            else:
                assert mode in (0, stat.S_IFREG)
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output)
    archive_path.unlink()
    return metadata


def main(root):
    root.mkdir()
    assert shutil.disk_usage(root).free >= 12 * 1024**3
    build, jobs = run_identity(BUILD_RUN, BUILD_HEAD, "openclaw-artifacts.yml")
    assert build["conclusion"] == "failure"
    required = {"build (" + label + ")" for label in ORIGINAL if label.startswith("bun-webkit-")} | {"windows-arm64"}
    assert len(required) == 11 and all(jobs[name]["conclusion"] == "success" and jobs[name]["run_attempt"] == 1 for name in required)
    replay, jobs = run_identity(REPLAY_RUN, REPLAY_HEAD, "openclaw-hosted-linux-consumer.yml")
    assert replay["conclusion"] == "success" and jobs["linux-native"]["conclusion"] == "success"
    artifacts = api(f"actions/runs/{REPLAY_RUN}/artifacts?per_page=100")["artifacts"]
    admitted = []
    for label in ("hosted-linux-native-proof", "hosted-linux-bun-executables"):
        matches = [item for item in artifacts if item["name"] == label]
        assert len(matches) == 1
        item = matches[0]
        assert item["size_in_bytes"] <= (8 * 1024**2 if label.endswith("proof") else 512 * 1024**2)
        admitted.append(download(root, label, [item["id"], item["size_in_bytes"], item["digest"]], REPLAY_RUN, REPLAY_HEAD))
    proof = root / "hosted-linux-native-proof"
    record, complete = read(proof / "matrix-replay.json"), read(proof / "matrix-replay-complete.json")
    assert record["run"] == BUILD_RUN and record["carrier"] == BUILD_HEAD and record["sync"] == SOURCE
    assert record["source"] == "2323913322dfdfed96ecf20163d62f5ff2796ecc"
    assert record["candidate_build_reused"] is True and record["candidate_runtime_evidence_reused"] is False
    assert record["manifest_sha256"] == "96d5eb1558b84d13b09e7ff1c56904a6834f72ad43d5558c92ad42e5ae75feb2"
    assert record["replay_control_sha256"] == "73f7154030e02bb01fbf0e2d62c77d17aac5c7a94e05ca022e6b26eebfd1d66d"
    assert complete["passed"] is True and complete["replay_sha256"] == sha(proof / "matrix-replay.json")
    assert complete["gate_sha256"] == sha(proof / "gate.json")
    assert complete["candidate_identity_sha256"] == record["candidate_identity_sha256"] == sha(proof / "candidate-identity.json")
    for name, digest in record["reused_files"].items():
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert sha(proof / path) == digest, name
    (root / "hosted-linux-native-proof").rename(root / "qualification")
    (root / "hosted-linux-bun-executables").rename(root / "linux-bun-executables")
    for label, row in ORIGINAL.items():
        admitted.append(download(root, label, row, BUILD_RUN, BUILD_HEAD))
    (root / "assembly-inputs.json").write_text(json.dumps({"source": SOURCE, "build_run": BUILD_RUN,
        "replay_run": REPLAY_RUN, "artifacts": admitted}, indent=2) + "\n")



def current21(root, pipeline):
    assert subprocess.check_output(["git", "-C", str(pipeline), "rev-parse", "HEAD"], text=True).strip() == CURRENT_SOURCE
    subprocess.run(["git", "-C", str(pipeline), "diff", "--exit-code", "HEAD"], check=True)
    config = read(pipeline / ".github/openclaw/variants.json")
    labels = {lane["label"] for lane in config["lanes"]}
    assert len(labels) == 21 and set(CURRENT_ARTIFACTS) == labels | {"windows-arm64-qualification"}
    root.mkdir()
    # Retain one extracted input set and one assembled copy; ZIPs are removed per lane.
    assert shutil.disk_usage(root).free >= 32 * 1024**3
    build, jobs = run_identity(CURRENT_BUILD_RUN, CURRENT_SOURCE, "openclaw-artifacts.yml")
    assert build["conclusion"] == "failure"
    required = {"build (" + label + ")" for label in labels} | {"windows-arm64", "preflight"}
    assert all(jobs[name]["conclusion"] == "success" and jobs[name]["run_attempt"] == 1 for name in required)
    assert jobs["test"]["conclusion"] == "failure"
    replay, replay_jobs = run_identity(CURRENT_REPLAY_RUN, CURRENT_REPLAY_HEAD, "openclaw-current-matrix-consumer.yml")
    assert replay["conclusion"] == "success"
    assert set(replay_jobs) == {"matrix-consumer"}
    assert replay_jobs["matrix-consumer"]["conclusion"] == "success" and replay_jobs["matrix-consumer"]["run_attempt"] == 1
    artifacts = api(f"actions/runs/{CURRENT_REPLAY_RUN}/artifacts?per_page=100")["artifacts"]
    admitted = []
    for label in ("current-matrix-linux-consumer-proof", "current-matrix-linux-bun-executables"):
        matches = [item for item in artifacts if item["name"] == label]
        assert len(matches) == 1
        item = matches[0]
        assert item["size_in_bytes"] <= (8 * 1024**2 if label.endswith("proof") else 512 * 1024**2)
        admitted.append(download(root, label, [item["id"], item["size_in_bytes"], item["digest"]], CURRENT_REPLAY_RUN, CURRENT_REPLAY_HEAD))
    proof = root / "current-matrix-linux-consumer-proof"
    record, complete = read(proof / "current-matrix-reuse.json"), read(proof / "current-matrix-complete.json")
    assert record["run"] == CURRENT_BUILD_RUN and record["head"] == CURRENT_SOURCE and record["carrier"] == CURRENT_REPLAY_HEAD
    assert record["baseline_build_reused"] is True and record["engine_evidence_reused"] is True
    assert all(record[key] is False for key in ("baseline_tests_reused", "candidate_build_reused", "candidate_tests_reused"))
    assert record["controller_sha256"] == CURRENT_CONTROLLER_SHA256
    assert record["pipeline_driver_sha256"] == sha(pipeline / ".github/openclaw/qualify.sh")
    assert record["driver_sha256"] == sha(proof / "qualify-current-matrix.sh")
    assert record["reference_tools_sha256"] == sha(proof / "reference-tools.json")
    assert record["admission_sha256"] == sha(proof / "current-matrix-admission.json")
    assert record["reused_files"] == CURRENT_REUSED_FILES
    for name, digest in CURRENT_REUSED_FILES.items():
        assert sha(proof / name) == digest, name
    admission = read(proof / "current-matrix-admission.json")
    assert admission["run"] == CURRENT_BUILD_RUN and admission["head"] == CURRENT_SOURCE
    assert complete["passed"] is True and complete["source"] == CURRENT_SOURCE
    assert complete["reuse_sha256"] == sha(proof / "current-matrix-reuse.json")
    assert complete["gate_sha256"] == sha(proof / "gate.json")
    assert complete["candidate_identity_sha256"] == sha(proof / "candidate-identity.json")
    (root / "current-matrix-linux-consumer-proof").rename(root / "qualification")
    (root / "current-matrix-linux-bun-executables").rename(root / "linux-bun-executables")
    for label, row in CURRENT_ARTIFACTS.items():
        admitted.append(download(root, label, row, CURRENT_BUILD_RUN, CURRENT_SOURCE, max_archive_bytes=2 * 1024**3))
    (root / "assembly-inputs.json").write_text(json.dumps({"source": CURRENT_SOURCE,
        "build_run": CURRENT_BUILD_RUN, "replay_run": CURRENT_REPLAY_RUN,
        "replay_head": CURRENT_REPLAY_HEAD, "successful_build_jobs": {name: jobs[name]["id"] for name in sorted(required)},
        "artifacts": admitted}, indent=2) + "\n")

if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "current21":
        current21(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
    else:
        main(Path(sys.argv[1]).resolve())
