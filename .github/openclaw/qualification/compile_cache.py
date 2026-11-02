"""Require the original compile-cache cases from the existing native module run."""
import base64
import hashlib
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

MODULE = 'test/js/node/module/node-module-module.test.js'
CASES = [( 'compile cache exit modes > node-module-module',
           f'compile cache persists correctly on {mode} exit with uncached modules')
         for mode in ('natural', 'exit', 'SIGTERM', 'SIGINT', 'SIGHUP', 'SIGUSR1',
                      'SIGTERM-self', 'SIGTERM-during-exit')]
CASES.append(('node-module-module', 'compile cache wakes an idle loop for deferred modules'))


def evidence(path):
    data = path.read_bytes()
    root = ET.fromstring(data)
    if root.tag != 'testsuites' or root.find('.//failure') is not None or root.find('.//error') is not None:
        raise ValueError('compile-cache JUnit contains failures or errors')
    rows = list(root.iter('testcase'))
    for classname, name in CASES:
        matches = [row for row in rows if (row.get('classname'), row.get('name')) == (classname, name)]
        if (len(matches) != 1 or matches[0].get('file') != MODULE
                or list(matches[0])):
            raise ValueError('compile-cache case missing, duplicated, skipped or failed: ' + name)
    return {'junit_sha256': hashlib.sha256(data).hexdigest(),
            'cases': [{'classname': classname, 'name': name} for classname, name in CASES]}


def collect(temp, prefix, output):
    if re.fullmatch(r'openclaw-sync-junit-[0-9a-f]{32}-', prefix) is None:
        raise ValueError('invalid compile-cache JUnit run prefix')
    directories = list(temp.glob(prefix + '*'))
    if len(directories) != 1 or not directories[0].is_dir() or directories[0].is_symlink():
        raise ValueError('expected one current-run JUnit directory')
    name = base64.urlsafe_b64encode(hashlib.sha1(MODULE.encode()).digest()).decode().rstrip('=')
    source = directories[0] / ('test-' + name + '.xml')
    if not source.is_file() or source.is_symlink():
        raise ValueError('current module JUnit report missing')
    with output.open('xb') as stream:
        stream.write(source.read_bytes())
    evidence(output)


if __name__ == '__main__':
    collect(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
