"""Recover marker-owned DVGA pastes, audit records, and exact uploaded test files."""

from __future__ import annotations

import json
import subprocess

NATIVE_HELPER = r"""
import json,sys,sqlite3,pathlib
v=json.load(sys.stdin);marker=v['marker'];c=sqlite3.connect('/opt/dvga/dvga.db');c.row_factory=sqlite3.Row
c.execute('BEGIN IMMEDIATE')
pastes=[dict(r) for r in c.execute('SELECT * FROM pastes WHERE user_agent=? ORDER BY id',(marker,))]
audits=[dict(r) for r in c.execute('SELECT * FROM audits WHERE gqloperation=? ORDER BY id',(marker,))]
root=pathlib.Path('/opt/dvga/pastes/')
files={}
for directory in [root,pathlib.Path('/tmp'),pathlib.Path('/etc'),pathlib.Path('/var/log')]:
 for path in directory.glob(marker+'-*'):
  if path.is_symlink() or not path.is_file():raise ValueError('unsafe DVGA owned upload')
  content=path.read_bytes()
  if content not in ((marker+':traversal test').encode(),(marker+':normal content').encode()):raise ValueError('changed DVGA upload bytes')
  files[str(path)]=content.decode()
if v['action']=='snapshot':
 if pastes or audits or files:raise ValueError('DVGA marker already present')
else:
 for path in files:pathlib.Path(path).unlink()
 c.execute('DELETE FROM pastes WHERE user_agent=?',(marker,));c.execute('DELETE FROM audits WHERE gqloperation=?',(marker,))
 pastes=[];audits=[];files={}
c.commit();print(json.dumps({'pastes':pastes,'audits':audits,'files':files}))
"""


def dvga_database(container: str, action: str, marker: str) -> dict:
    """Verify exact Compose ownership before native marker cleanup."""
    data = json.loads(
        subprocess.check_output(  # noqa: S603 - fixed declared Docker inventory
            ["/usr/bin/docker", "inspect", container], text=True, timeout=10
        )
    )[0]
    labels = data.get("Config", {}).get("Labels", {})
    if (
        labels.get("com.docker.compose.project") != "origin-server"
        or labels.get("com.docker.compose.service") != container
        or labels.get("org.f5.demo.application") != "dvga"
    ):
        message = "DVGA replica ownership mismatch"
        raise ValueError(message)
    result = subprocess.run(  # noqa: S603 - fixed native helper and structured marker
        [
            "/usr/bin/docker",
            "exec",
            "-i",
            container,
            "python3",
            "-B",
            "-c",
            NATIVE_HELPER,
        ],
        input=json.dumps({"action": action, "marker": marker}),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)
