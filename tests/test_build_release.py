"""Release archives must not publish the machine identities found in raw builds."""

from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import stat
import struct
import tarfile
import zipfile

import pytest

from scripts.build_release import (
    check_metadata, check_private_paths, normalize_sdist, normalize_wheel,
)


ROOT = Path(__file__).resolve().parents[1]
EPOCH = 1700000000


def test_sdist_repack_removes_machine_identity_without_rewriting_licenses(tmp_path):
    payloads = {
        "contextproof/LICENSE": (ROOT / "LICENSE").read_bytes(),
        "contextproof/benchmarks/upstream/LICENSE":
            (ROOT / "benchmarks/downstream/upstream/LICENSE").read_bytes(),
        "contextproof/src/contextproof/__init__.py":
            (ROOT / "src/contextproof/__init__.py").read_bytes(),
    }
    normalized = []
    for number, owner in enumerate(("private-builder-a", "private-builder-b")):
        raw, checked = tmp_path / f"raw-{number}.tar.gz", tmp_path / f"checked-{number}.tar.gz"
        with tarfile.open(raw, "w:gz") as archive:
            for name, content in reversed(list(payloads.items())):
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                entry.uid = entry.gid = 501 + number
                entry.uname = entry.gname = owner
                entry.linkname = owner
                entry.mtime = EPOCH + number
                entry.pax_headers = {"comment": owner, "atime": str(EPOCH + number)}
                archive.addfile(entry, io.BytesIO(content))
        normalize_sdist(raw, checked, EPOCH)
        normalized.append(checked.read_bytes())
        with tarfile.open(checked) as archive:
            members = archive.getmembers()
            assert {member.name: archive.extractfile(member).read()
                    for member in members} == payloads
            assert all((member.uid, member.gid, member.uname, member.gname, member.mtime)
                       == (0, 0, "", "", EPOCH) for member in members)
            assert all(not member.pax_headers and not member.linkname for member in members)
    assert hashlib.sha256(normalized[0]).digest() == hashlib.sha256(normalized[1]).digest()


def test_wheel_repack_removes_zip_identity_and_preserves_executable_payload(tmp_path):
    outputs = []
    for number in range(2):
        raw, checked = tmp_path / f"raw-{number}.whl", tmp_path / f"checked-{number}.whl"
        with zipfile.ZipFile(raw, "w") as archive:
            entry = zipfile.ZipInfo("contextproof.data/scripts/tool", (2024 + number, 1, 1, 0, 0, 0))
            entry.external_attr = (stat.S_IFREG | 0o755) << 16
            entry.comment = b"private-builder"
            uid_extra = bytes([1, 4]) + struct.pack("<I", 501 + number)
            entry.extra = struct.pack("<HH", 0x7875, len(uid_extra)) + uid_extra
            archive.writestr(entry, b"#!/usr/bin/env python3\nprint('ready')\n")
        normalize_wheel(raw, checked, EPOCH)
        outputs.append(checked.read_bytes())
        with zipfile.ZipFile(checked) as archive:
            entry = archive.infolist()[0]
            assert not entry.extra and not entry.comment and not archive.comment
            assert entry.date_time == datetime.fromtimestamp(EPOCH, timezone.utc).timetuple()[:6]
            assert entry.external_attr >> 16 & 0o777 == 0o755
            assert archive.read(entry) == b"#!/usr/bin/env python3\nprint('ready')\n"
    assert outputs[0] == outputs[1]


def test_release_guards_reject_identity_metadata_and_embedded_home_paths():
    with pytest.raises(ValueError, match="public maintainer"):
        check_metadata(b"Name: contextproof\nVersion: 1.0.0\nAuthor: Private Builder\n",
                       "contextproof", "1.0.0")
    for parts in (("", "Users", "private-builder", "source.py"),
                  ("", "home", "private-builder", "source.py")):
        with pytest.raises(ValueError, match="personal home path"):
            check_private_paths("/".join(parts).encode())
