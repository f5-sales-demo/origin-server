#!/bin/bash
# Download one immutable origin archive and verify it before extraction or execution.
set -euo pipefail
COMMIT="${1:?origin commit required}"
ARCHIVE_SHA="${2:?origin archive SHA-256 required}"
INSTALLER_SHA="${3:?origin installer SHA-256 required}"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ && "$ARCHIVE_SHA" =~ ^[0-9a-f]{64}$ && "$INSTALLER_SHA" =~ ^[0-9a-f]{64}$ ]]
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
curl --fail --location --retry 3 --max-time 180 "https://codeload.github.com/f5-sales-demo/origin-server/tar.gz/${COMMIT}" -o "$STAGE/origin.tar.gz"
printf '%s  %s\n' "$ARCHIVE_SHA" "$STAGE/origin.tar.gz" | sha256sum --check --status
python3 - "$STAGE/origin.tar.gz" "$STAGE/source" <<'PY'
import pathlib, sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    members = archive.getmembers()
    if any(member.issym() or member.islnk() or member.name.startswith('/') or '..' in pathlib.PurePosixPath(member.name).parts for member in members):
        raise ValueError('unsafe immutable origin archive')
    archive.extractall(sys.argv[2], filter='data')
PY
SOURCE="$STAGE/source/origin-server-$COMMIT"
printf '%s  %s\n' "$INSTALLER_SHA" "$SOURCE/scripts/install_origin.py" | sha256sum --check --status
ORIGIN_SOURCE_COMMIT="$COMMIT" ORIGIN_ARCHIVE_SHA256="$ARCHIVE_SHA" ORIGIN_INSTALLER_SHA256="$INSTALLER_SHA" python3 "$SOURCE/scripts/install_origin.py" --provision
