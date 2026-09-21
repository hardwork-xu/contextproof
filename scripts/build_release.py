#!/usr/bin/env python3
"""Build checked release archives without local ownership or home-path metadata.

Install ``.[dev]``, then run ``python scripts/build_release.py
--source-date-epoch EPOCH --out dist`` from a clean release checkout. The epoch
may instead be supplied as SOURCE_DATE_EPOCH; it never defaults to wall time.
Reproducibility requires the same source, Python, build frontend and backend.
Use --no-isolation with a separately pinned build environment when appropriate.
Only validated, normalized artifacts are copied into the empty output directory.
Third-party license contents are preserved without modification.
"""

from __future__ import annotations

import argparse
import base64
import copy
import csv
from datetime import datetime, timezone
from email.parser import BytesParser
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile


PUBLIC_MAINTAINER = "hardwork-xu"
HOME_PATH = re.compile(
    rb"(?i)(?:/(?:Users|home)/[^/\s\"'<>]+|[a-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>]+)"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_private_paths(raw: bytes) -> None:
    home = str(Path.home()).encode()
    require(not HOME_PATH.search(raw), "artifact contains a personal home path")
    require(home in {b"/", b"."} or home not in raw,
            "artifact contains the current user's home directory")


def check_member_name(name: str) -> None:
    path = PurePosixPath(name)
    require(bool(path.parts) and not path.is_absolute()
            and ".." not in path.parts and "\\" not in name,
            "archive contains an unsafe member path")
    check_private_paths(name.encode())


def normalize_sdist(source: Path, target: Path, epoch: int) -> None:
    """Canonicalize headers without changing any member's payload bytes."""
    with tarfile.open(source) as original, target.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as result:
                for member in sorted(original.getmembers(), key=lambda item: item.name):
                    check_member_name(member.name)
                    require(member.isfile() or member.isdir(),
                            "source distribution contains a link or special file")
                    entry = copy.copy(member)
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = ""
                    entry.linkname = ""
                    entry.devmajor = entry.devminor = 0
                    entry.type = tarfile.DIRTYPE if member.isdir() else tarfile.REGTYPE
                    entry.mtime = epoch
                    entry.mode = 0o755 if entry.isdir() or member.mode & 0o111 else 0o644
                    entry.pax_headers = {}
                    result.addfile(entry, original.extractfile(member) if member.isfile() else None)


def normalize_wheel(source: Path, target: Path, epoch: int) -> None:
    """Remove ZIP extras/comments and normalize time while retaining executable bits."""
    moment = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc)
    date_time = (*moment.timetuple()[:5], moment.second // 2 * 2)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as result:
        for member in sorted(original.infolist(), key=lambda item: item.filename):
            check_member_name(member.filename)
            mode = member.external_attr >> 16
            require(not stat.S_ISLNK(mode), "wheel contains a symbolic link")
            entry = zipfile.ZipInfo(member.filename, date_time)
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            permissions = 0o755 if member.is_dir() or mode & 0o111 else 0o644
            kind = stat.S_IFDIR if member.is_dir() else stat.S_IFREG
            entry.external_attr = (kind | permissions) << 16
            result.writestr(entry, original.read(member), compresslevel=9)


def check_metadata(raw: bytes, name: str, version: str) -> None:
    check_private_paths(raw)
    metadata = BytesParser().parsebytes(raw)
    def canonical(value):
        return re.sub(r"[-_.]+", "-", value).lower()
    require(canonical(metadata.get("Name", "")) == canonical(name)
            and metadata.get("Version") == version, "package name/version mismatch")
    require(metadata.get_all("Author") == [PUBLIC_MAINTAINER]
            and not metadata.get_all("Author-email")
            and not metadata.get_all("Maintainer-email")
            and metadata.get_all("Maintainer", []) in ([], [PUBLIC_MAINTAINER]),
            "package identity metadata must use the public maintainer handle only")


def check_record(payloads: dict[str, bytes]) -> None:
    records = [name for name in payloads if name.endswith(".dist-info/RECORD")]
    require(len(records) == 1, "wheel must have one RECORD")
    names = []
    for name, integrity, size in csv.reader(io.StringIO(payloads[records[0]].decode())):
        names.append(name)
        require(name in payloads, "wheel RECORD references a missing file")
        if name == records[0]:
            require(not integrity and not size, "wheel RECORD must not hash itself")
            continue
        raw = payloads[name]
        expected = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        require(integrity == "sha256=" + expected and size == str(len(raw)),
                "wheel RECORD content hash mismatch")
    require(len(names) == len(set(names)) and set(names) == set(payloads),
            "wheel RECORD does not cover exactly the wheel payload")


def validate_artifacts(wheel: Path, sdist: Path, project: dict, license_bytes: bytes,
                       epoch: int) -> str:
    require(PUBLIC_MAINTAINER.encode() in license_bytes,
            "project LICENSE must identify the public maintainer")
    check_private_paths(license_bytes)
    name, version = project["name"], project["version"]
    with zipfile.ZipFile(wheel) as archive:
        members = archive.infolist()
        require(len(members) == len({member.filename for member in members}),
                "wheel contains duplicate member names")
        payloads = {}
        for member in members:
            check_member_name(member.filename)
            require(not member.extra and not member.comment, "wheel retains private ZIP extras")
            raw = archive.read(member)
            check_private_paths(raw)
            if not member.is_dir():
                payloads[member.filename] = raw
    metadata = [raw for path, raw in payloads.items() if path.endswith(".dist-info/METADATA")]
    licenses = [raw for path, raw in payloads.items() if path.endswith(".dist-info/licenses/LICENSE")]
    require(len(metadata) == 1 and licenses == [license_bytes],
            "wheel metadata or owned LICENSE is missing/changed")
    check_metadata(metadata[0], name, version)
    check_record(payloads)
    wheel_info = [raw for path, raw in payloads.items() if path.endswith(".dist-info/WHEEL")]
    require(len(wheel_info) == 1, "wheel build metadata is missing")
    generator = BytesParser().parsebytes(wheel_info[0]).get("Generator", "unknown")
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        require(len(members) == len({member.name for member in members}),
                "source distribution contains duplicate member names")
        roots = {PurePosixPath(member.name).parts[0] for member in members}
        require(len(roots) == 1, "source distribution must have one root")
        payloads = {}
        for member in members:
            check_member_name(member.name)
            require(member.uid == member.gid == 0 and not member.uname and not member.gname,
                    "source archive retains local ownership")
            require(not member.linkname, "source archive retains unexpected link metadata")
            require(member.mtime == epoch, "source archive timestamp differs from declared epoch")
            require(set(member.pax_headers) <= {"path", "size"},
                    "source archive retains unexpected extended metadata")
            require(member.isfile() or member.isdir(), "source archive contains a special file")
            if member.isfile():
                raw = archive.extractfile(member).read()
                check_private_paths(raw)
                payloads[member.name.partition("/")[2]] = raw
        require(payloads.get("LICENSE") == license_bytes, "source LICENSE is missing/changed")
        require("PKG-INFO" in payloads, "source metadata is missing")
        check_metadata(payloads["PKG-INFO"], name, version)
    return generator


def build_release(source: Path, output: Path, epoch: int, no_isolation: bool = False) -> list[Path]:
    require(0 <= epoch <= 0xFFFFFFFF, "SOURCE_DATE_EPOCH must fit an unsigned 32-bit timestamp")
    source, output = source.resolve(), output.resolve()
    require(not output.exists() or output.is_dir() and not any(output.iterdir()),
            "release output must be an empty directory")
    project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
    require(project.get("authors") == [{"name": PUBLIC_MAINTAINER}],
            "project authors must declare the public maintainer handle only")
    license_bytes = (source / "LICENSE").read_bytes()
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch), "PYTHONHASHSEED": "0"}
    with tempfile.TemporaryDirectory(prefix="contextproof-release-") as temporary:
        work = Path(temporary)
        raw, checked = work / "raw", work / "checked"
        checked.mkdir()
        command = [sys.executable, "-m", "build", "--outdir", str(raw)]
        if no_isolation:
            command.append("--no-isolation")
        command.append(str(source))
        subprocess.run(command, env=env, check=True)
        wheels, sdists = list(raw.glob("*.whl")), list(raw.glob("*.tar.gz"))
        require(len(wheels) == len(sdists) == 1, "build must produce one wheel and one source archive")
        wheel, sdist = checked / wheels[0].name, checked / sdists[0].name
        normalize_wheel(wheels[0], wheel, epoch)
        normalize_sdist(sdists[0], sdist, epoch)
        generator = validate_artifacts(wheel, sdist, project, license_bytes, epoch)
        info = {
            "name": project["name"], "version": project["version"],
            "source_date_epoch": epoch, "maintainer": PUBLIC_MAINTAINER,
            "python": platform.python_version(), "build": importlib.metadata.version("build"),
            "wheel_generator": generator, "isolated_build": not no_isolation,
            "reproducibility_scope": "identical source, epoch, Python and build toolchain",
            "archive_ownership": {"uid": 0, "gid": 0, "uname": "", "gname": ""},
        }
        (checked / "BUILDINFO.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
        artifacts = sorted(checked.iterdir())
        sums = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
                       for path in artifacts)
        (checked / "SHA256SUMS").write_text(sums)
        output.mkdir(parents=True, exist_ok=True)
        for path in checked.iterdir():
            shutil.copyfile(path, output / path.name)
    return sorted(output.iterdir())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument("--source-date-epoch", type=int, default=os.environ.get("SOURCE_DATE_EPOCH"))
    parser.add_argument("--no-isolation", action="store_true")
    arguments = parser.parse_args()
    if arguments.source_date_epoch is None:
        parser.error("declare --source-date-epoch or SOURCE_DATE_EPOCH")
    try:
        artifacts = build_release(arguments.source, arguments.out, arguments.source_date_epoch,
                                  arguments.no_isolation)
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Release build failed: {error}\n")
    for path in artifacts:
        print(path.name)


if __name__ == "__main__":
    main()
