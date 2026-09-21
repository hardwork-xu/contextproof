#!/usr/bin/env python3
"""Generate an offline before/change/refresh demonstration from original fixtures."""

import argparse
import json
from pathlib import Path

from contextproof.report import render_report
from contextproof.session import capture_context, check_context, refresh_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("work/demo"))
    args = parser.parse_args()
    output = args.output
    root = output / "repository"
    root.mkdir(parents=True, exist_ok=True)
    (root / "policy.py").write_text("def tax_rate():\n    return 0.10\n", encoding="utf-8")
    (root / "checkout.py").write_text(
        "from policy import tax_rate\n\ndef invoice_total(amount):\n"
        "    return amount * (1 + tax_rate())\n", encoding="utf-8")
    original = capture_context(root, "invoice_total", budget=6000)
    before = check_context(original, root)
    (output / "01-before.html").write_text(render_report(original, before), encoding="utf-8")
    (root / "policy.py").write_text("def tax_rate():\n    return 0.12\n", encoding="utf-8")
    changed = check_context(original, root)
    (output / "02-changed.html").write_text(render_report(original, changed), encoding="utf-8")
    updated = refresh_context(original, root)
    after = check_context(updated, root)
    (output / "03-refreshed.html").write_text(render_report(updated, after), encoding="utf-8")
    for name, value in (("original.json", original), ("changed.json", changed),
                        ("refreshed.json", updated)):
        (output / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
    if not (before["can_reuse"] and changed["source"]["valid"]
            and not changed["can_reuse"] and after["can_reuse"]):
        raise RuntimeError("demo contract failed; inspect the generated reports")
    print(json.dumps({"before": before["recommendation"],
                      "after_dependency_edit": changed["recommendation"],
                      "after_refresh": after["recommendation"],
                      "report_directory": str(output)}, indent=2))


if __name__ == "__main__":
    main()
