# Public project, private records

The public repository contains source, technical decisions, reproducible inputs,
sanitized experiment records and limitations. Its maintainer identity is the
public GitHub handle. AI assistance remains disclosed.

Personal learning plans, career material, private account details, raw local
runtime logs and backups belong outside the Git checkout. Do not add credentials,
home-directory paths, account identifiers or unfiltered terminal transcripts.
Public experiment exports retain model answers, failures, timings and usage;
redactions and both original/exported content hashes are recorded explicitly.
Privacy cleanup must never silently alter scores or hide unsuccessful attempts.

Before publishing, run `python scripts/check_publication.py`. An optional
`--private-rules` JSON file outside the repository adds personal strings to check;
the checker reports locations without printing the private values. Review binary
release assets and commit metadata separately. Existing third-party attribution
and source licenses must remain intact.

## Release archives

Use the checked archive builder from a clean checkout, with a declared timestamp:

```sh
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
  python scripts/build_release.py --out dist
```

The output directory must be empty. The builder normalizes archive ownership and
timestamps, validates package identity and wheel content hashes, and produces
`BUILDINFO.json` and `SHA256SUMS`. It preserves third-party license bytes. Identical
artifacts require identical source, timestamp and Python/build toolchain; the
recorded toolchain is not a promise that an unpinned future build is identical.
Use `--no-isolation` with a separately pinned environment when reproducing one.
