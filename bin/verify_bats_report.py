#!/usr/bin/env python3
"""Verify a bats TAP report proves bin/tests/*.bats actually ran (hindsight#170).

Closes the accidental/careless silencing case for the bin-tool bats step: a
missing, empty, malformed, under-count, failing, or title-forged TAP report
fails loudly (nonzero exit). The fully-coordinated adversarial case (edit
producer + consumer + pin together) remains open — hindsight#171.

Usage:
  python3 bin/verify_bats_report.py <report.tap> <tests-dir>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# bats TAP result lines: "ok N description" / "not ok N description".
# Only TAP directives (# SKIP / # TODO, any case) are stripped — a literal '#'
# inside a test title (e.g. "issue #89") is part of the description. Bats emits
# skips as: ok 1 title # skip reason
_RESULT_RE = re.compile(
    r"^(?P<not>not )?ok\s+(?P<num>\d+)\s+(?P<body>\S.*)$"
)
_DIRECTIVE_RE = re.compile(
    r"^(?P<desc>.*?)\s+#\s*(?P<dir>(?:SKIP|TODO)\b.*)$",
    re.IGNORECASE,
)
# Canonical shape in this repo: @test "title" {
_AT_TEST_RE = re.compile(r'^\s*@test\s+"((?:\\.|[^"\\])*)"\s*\{?\s*$')


def _die(msg: str, code: int = 1) -> None:
    print(f"verify_bats_report: ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _unescape_dquote_title(raw: str) -> str:
    """Undo bash double-quote backslash escaping for an @test "title" body.

    A bats @test title is parsed by bash as a double-quoted string, where a
    backslash retains its special meaning only before $, `, ", \\, or a
    newline (which it splices away); every other backslash+char sequence
    passes through literally. Without this, a title containing e.g. \\$RC
    is captured here as the two characters '\\$RC', but bats reports the
    *evaluated* title '$RC' in its TAP output -- a real mismatch that made a
    legitimate title fail the cross-reference (hindsight#170 CI: guard
    (tools) run 32856407100, bin/tests/test_require_real_ci.bats:390).
    """
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == "\\" and i + 1 < n and raw[i + 1] in ('$', '`', '"', '\\', '\n'):
            nxt = raw[i + 1]
            if nxt != "\n":
                out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def collect_source_titles(tests_dir: Path) -> list[str]:
    """Return @test titles from *.bats under tests_dir, in file/line order."""
    if not tests_dir.is_dir():
        _die(f"tests directory missing: {tests_dir}")
    bats_files = sorted(tests_dir.glob("*.bats"))
    if not bats_files:
        _die(f"no *.bats files under {tests_dir}")
    titles: list[str] = []
    for path in bats_files:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            _die(f"empty bats file: {path}")
        for line_no, line in enumerate(text.splitlines(), 1):
            match = _AT_TEST_RE.match(line)
            if match:
                titles.append(_unescape_dquote_title(match.group(1)))
            elif re.match(r"^\s*@test\b", line):
                _die(
                    f"unsupported @test shape at {path}:{line_no}: {line.strip()!r} "
                    "(expected @test \"title\")"
                )
    if not titles:
        _die(f"zero @test cases under {tests_dir}")
    return titles


def parse_tap_results(report: Path) -> list[tuple[bool, int, str]]:
    """Parse ok/not-ok result lines from a TAP file. Fail loud on absence."""
    if not report.is_file():
        _die(f"TAP report missing: {report}")
    raw = report.read_bytes()
    if not raw.strip():
        _die(f"TAP report empty: {report}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _die(f"TAP report is not UTF-8: {report}: {exc}")

    results: list[tuple[bool, int, str]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#") or line.startswith(" "):
            continue
        if line.startswith("1..") or line.startswith("Bail out!"):
            continue
        match = _RESULT_RE.match(line)
        if match is None:
            # Ignore unknown TAP non-result lines (YAML blocks, plan variants).
            continue
        passed = match.group("not") is None
        number = int(match.group("num"))
        body = match.group("body").strip()
        directive = _DIRECTIVE_RE.match(body)
        desc = directive.group("desc").strip() if directive else body
        if not desc:
            _die(f"TAP result with empty description at {report}:{line_no}")
        results.append((passed, number, desc))
    if not results:
        _die(
            f"TAP report has zero ok/not ok result lines: {report} "
            "(absent or malformed report reads the same as 'did not run')"
        )
    return results


def verify(report: Path, tests_dir: Path) -> None:
    source_titles = collect_source_titles(tests_dir)
    floor = len(source_titles)
    source_set = set(source_titles)
    if len(source_set) != floor:
        _die(
            f"duplicate @test titles under {tests_dir}: "
            f"{floor} cases but {len(source_set)} unique titles"
        )

    results = parse_tap_results(report)
    failures = [(n, d) for ok, n, d in results if not ok]
    if failures:
        sample = "; ".join(f"not ok {n} {d}" for n, d in failures[:5])
        more = "" if len(failures) <= 5 else f" (+{len(failures) - 5} more)"
        _die(f"TAP report contains {len(failures)} failing case(s): {sample}{more}")

    if len(results) != floor:
        _die(
            f"TAP result count {len(results)} != live @test floor {floor} "
            f"from {tests_dir}/*.bats"
        )

    tap_descs = [desc for _, _, desc in results]
    tap_set = set(tap_descs)
    unknown = sorted(tap_set - source_set)
    if unknown:
        sample = ", ".join(repr(t) for t in unknown[:5])
        more = "" if len(unknown) <= 5 else f" (+{len(unknown) - 5} more)"
        _die(
            f"TAP descriptions not present as @test titles in {tests_dir}: "
            f"{sample}{more}"
        )
    missing = sorted(source_set - tap_set)
    if missing:
        sample = ", ".join(repr(t) for t in missing[:5])
        more = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
        _die(
            f"live @test titles missing from TAP report: {sample}{more}"
        )
    if len(tap_descs) != len(tap_set):
        _die(
            f"TAP report repeats titles ({len(tap_descs)} results, "
            f"{len(tap_set)} unique) — refusing padded forgery"
        )

    print(
        f"verify_bats_report: OK ({len(results)} cases, "
        f"titles cross-checked against {tests_dir})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail unless a bats TAP report matches the live @test floor and "
            "titles under a tests directory (hindsight#170)."
        )
    )
    parser.add_argument("report", type=Path, help="path to report.tap")
    parser.add_argument(
        "tests_dir",
        type=Path,
        help="directory of *.bats sources (e.g. bin/tests)",
    )
    args = parser.parse_args(argv)
    verify(args.report, args.tests_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # stdout closed mid-write (e.g. piped to head) — still a success path.
        raise SystemExit(0)
