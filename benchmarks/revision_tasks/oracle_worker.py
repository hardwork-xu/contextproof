"""Trusted upstream behavior oracle, only launched under verified OS restrictions."""

from __future__ import annotations

import json
import resource
import sys
import warnings
from pathlib import Path


def main() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    payload = json.loads(Path(sys.argv[1]).read_text())
    sys.path[:0] = payload["import_paths"]
    # Do not turn deprecation warnings into errors. Warning tasks capture their own.
    warnings.simplefilter("ignore")
    namespace = {"__name__": "revision_probe"}
    try:
        # An import failure indicates a broken environment, not a task answer.
        __import__(payload["import_name"])
    except BaseException as exc:
        print(json.dumps({"harness_error": type(exc).__name__, "message": str(exc)}))
        return
    try:
        exec(compile(payload["code"], "probe.py", "exec"), namespace)
        answer = {"value": namespace["RESULT"]}
        encoded = json.dumps(answer, sort_keys=True, allow_nan=False)
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as exc:
        encoded = json.dumps({"error": type(exc).__name__}, sort_keys=True)
    print(encoded)


if __name__ == "__main__":
    main()
