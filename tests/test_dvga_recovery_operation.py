"""Functional recovery probes use the same accepted operation as native readiness."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_probe_matches_accepted_seeded_paste_operation():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"] == "/usr/local/bin/demo-dvga-recovery"
    )
    assert "query getPastes" in source
    assert "limit: 1" in source


def test_recovery_checks_running_container_provenance_and_compose_owner():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"] == "/usr/local/bin/demo-dvga-recovery"
    )
    assert 'container["Config"]' in source
    assert "com.docker.compose.project" in source
    assert "origin-server" in source


def test_busy_native_replica_survives_costly_operation_before_recovery(tmp_path):
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"] == "/usr/local/bin/demo-dvga-recovery"
    )
    state = tmp_path / "state.json"
    source = source.replace("/var/lib/demo-dvga-recovery.json", str(state))
    setup = """import subprocess, urllib.request, time, json, types
now = [1000]
time.time = lambda: now[0]
restarts = []
def run(args, **kwargs):
 if args[1] == 'inspect':
  name=args[2]
  return types.SimpleNamespace(stdout=json.dumps([{'Name':'/'+name,'Config':{'Labels':{'org.f5.demo.application':'dvga','org.f5.demo.base-sha256':'040aa33c199d99f3380c9ff9a1ee5d725e9abca7b189c63a35a2a73bda79c957','com.docker.compose.project':'origin-server','com.docker.compose.service':name,'com.docker.compose.project.working_dir':'/opt/origin-server'}}}]))
 restarts.append(args[2])
 return types.SimpleNamespace(stdout='')
subprocess.run = run
mock_healthy = [False]
class Response:
 def __enter__(self): return self
 def __exit__(self,*args): pass
 def read(self): return b'{"data":{"pastes":[{"id":"1"}]}}'
def open_url(*args,**kwargs):
 if mock_healthy[0]: return Response()
 raise TimeoutError('busy synthetic replica')
urllib.request.urlopen = open_url
"""
    script = tmp_path / "check.py"
    script.write_text(
        setup
        + "\nsource="
        + repr(source)
        + "\n"
        + """for stamp in [1000,1040,1080,1600]:
 now[0]=stamp
 exec(source)
assert not restarts, restarts
now[0]=1901
exec(source)
assert len(restarts)==4, restarts
mock_healthy[0]=True
now[0]=1940
exec(source)
assert all(v['unresponsive_since']==0 for v in json.loads(STATE.read_text()).values())
"""
    )
    result = subprocess.run(  # noqa: S603 - synthetic recovery process
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_load_adapter_preserves_delay_and_iteration_count():
    files = json.loads((ROOT / "provisioning/files.json").read_text())
    source = next(
        item["content"]
        for item in files
        if item["path"].endswith("dvga-adapter/adapt.py")
    )
    assert "cooperative_sleep(0.1)" in source
    assert "from gevent import sleep as cooperative_sleep" in source
    assert "loads =" not in source
