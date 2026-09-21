"""Keep raw local diagnostics off-repository; publish portable placeholders."""

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
PRIVATE = Path.home() / "Desktop" / "ContextProof-Private" / "baselines"


def public_value(value):
    replacements = [(str(PRIVATE.parent), "<PRIVATE_ARCHIVE>"),
                    (str(PROJECT), "<PROJECT>"),
                    (str(PROJECT.parents[1]), "<WORKSPACE>"),
                    (str(Path.home()), "<USER_HOME>")]
    if isinstance(value, str):
        for original, replacement in replacements:
            value = value.replace(original, replacement)
        return value
    if isinstance(value, dict):
        return {public_value(key): public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_value(item) for item in value]
    return value


def archive_raw(value, label):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    path = PRIVATE / f"{label}-{digest}.json"
    if not path.exists():
        path.write_bytes(raw)
    return digest


def public_record(value, label):
    digest = archive_raw(value, label)
    result = public_value(value)
    result["private_record_sha256"] = digest
    return result
