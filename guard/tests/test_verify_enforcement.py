"""Contract tests for the L1 enforcement-existence verifier.

The verifier resolves every non-null enforcement path against
the checkout root of the source it came from -- NOT against a single shared
directory. A path is one of three things:

  enforced      -- root known and present, path resolves.        (silent)
  phantom       -- root known and present, path does NOT resolve. (FATAL)
  UNVERIFIABLE  -- root unknown, or root known but absent on this machine.
                   Reported loudly with a count; never folded into "enforced".

And the whole check refuses to report success if it could not see anything:
zero resolved roots is an ERROR, not a vacuous pass.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "guard" / "failure_mode_catalog_guard.py"
SPEC = importlib.util.spec_from_file_location("failure_mode_catalog_guard", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_records(l1_dir: Path, source: str, *records: dict[object, object]) -> None:
    (l1_dir / f"{source}.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def write_source_roots(path: Path, mapping: dict[str, str]) -> None:
    lines = [f"{source}:{relpath}" for source, relpath in mapping.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_known_phantoms(path: Path, records: list[dict[str, str]]) -> None:
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_enforcement_floor(path: Path, floor: int | str) -> None:
    path.write_text(f"{floor}\n", encoding="utf-8")


def write_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


def write_runner_source(path: Path, contents: str) -> None:
    """Write a deliberately non-executable source file for a managed runner."""
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o664)


def run_verifier(
    monkeypatch: pytest.MonkeyPatch,
    l1_dir: Path,
    projects: Path,
    source_roots_path: Path,
    extra_args: list[str] | None = None,
    known_phantoms: list[dict[str, str]] | None = None,
    enforcement_floor: int | str | None = None,
    known_phantoms_path: Path | None = None,
    enforcement_floor_path: Path | None = None,
) -> int:
    """Drive main() with every default sandboxed to tmp_path.

    known_phantoms / enforcement_floor default to permissive, no-op values
    (an empty ledger, floor 0) so tests that don't care about the debt-
    ledger/floor gates aren't affected by them -- pass known_phantoms_path
    or enforcement_floor_path (pointing at a file you never created, or
    deliberately malformed) to exercise the "fails loud" behavior instead.
    """
    monkeypatch.setattr(MODULE, "default_l1_dir", lambda: l1_dir)
    monkeypatch.setattr(MODULE, "default_projects_dir", lambda: projects)
    monkeypatch.setattr(MODULE, "default_source_roots_path", lambda: source_roots_path)

    if known_phantoms_path is None:
        known_phantoms_path = l1_dir.parent / "known-phantoms.conf"
        write_known_phantoms(known_phantoms_path, known_phantoms or [])
    monkeypatch.setattr(MODULE, "default_known_phantoms_path", lambda: known_phantoms_path)

    if enforcement_floor_path is None:
        enforcement_floor_path = l1_dir.parent / "enforcement-floor.conf"
        write_enforcement_floor(enforcement_floor_path, 0 if enforcement_floor is None else enforcement_floor)
    monkeypatch.setattr(MODULE, "default_enforcement_floor_path", lambda: enforcement_floor_path)

    return MODULE.main(["--verify-enforcement", *(extra_args or [])])


def machine_record(id_: str, enforcement: dict[str, str] | None) -> dict[str, object]:
    return {"id": id_, "auto": "machine", "enforcement": enforcement}


def judgment_record(id_: str, enforcement: dict[str, str] | None) -> dict[str, object]:
    return {"id": id_, "auto": "judgment", "enforcement": enforcement}


# ---------------------------------------------------------------------------
# Baseline: root known and present.
# ---------------------------------------------------------------------------


def test_root_known_and_path_exists_is_enforced_and_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    err = capsys.readouterr().err
    assert "phantom:" not in err
    assert "control.py" not in err  # enforced entries are silent, not just non-fatal


def test_root_known_and_path_absent_is_phantom_names_entry_and_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing/control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    err = capsys.readouterr().err
    # Assert the exact rendered phantom line, not loose substrings -- "sample"
    # and "example" alone also appear in the always-printed per-source summary
    # row regardless of whether phantom detection ran at all, so a decorative
    # boilerplate print (or a deleted phantom-append) would pass those checks
    # for the wrong reason.
    assert "phantom: missing/control.py (sample:example," in err


@pytest.mark.parametrize("kind", ["test", "hook"])
def test_non_executable_stub_is_phantom_for_executable_mechanism_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """A present inert stub must not satisfy a test or hook enforcement claim."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    (repo / "decoy.sh").write_text("decoy\n", encoding="utf-8")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("decoy", {"file": "decoy.sh", "kind": kind}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    assert f"phantom: decoy.sh (sample:decoy," in capsys.readouterr().err


def test_non_executable_runner_managed_test_source_is_plausible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A test runner may execute a source file without its execute bit."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    (repo / "feature.test.js").write_text("test('feature', () => {});\n", encoding="utf-8")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir, "sample", machine_record("runner-test", {"file": "feature.test.js", "kind": "test"})
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    assert "phantom:" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("test_feature.py", "def test_feature():\n    assert True\n"),
        ("test_async.py", "async def test_feature():\n    assert True\n"),
        ("test_class.py", "class TestFeature:\n    async def test_feature(self):\n        assert True\n"),
        ("feature.bats", '@test "feature works" {\n  run true\n  [ "$status" -eq 0 ]\n}\n'),
    ],
)
def test_non_executable_structurally_valid_runner_sources_are_plausible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    filename: str,
    contents: str,
) -> None:
    """Mode-0664 Pytest and Bats sources are runner inputs, not inert stubs.

    This restores the old Pytest-positive direction that origin/main accepted
    before the executable-only predicate was introduced.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    runner_source = repo / filename
    write_runner_source(runner_source, contents)
    assert runner_source.stat().st_mode & 0o777 == 0o664
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("runner-test", {"file": filename, "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    assert "phantom:" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("test_decoy.py", "# def test_comment():\npass\n"),
        ("test_decoy.py", '"def test_string(): pass"\n'),
        ("test_decoy.py", "test_name = True\n"),
        ("test_decoy.py", "def test_broken(:\n    pass\n"),
        ("test_decoy.py", "class TestOnly:\n    pass\n"),
        ("decoy.bats", "# @test \"commented\" { true; }\n"),
        ("decoy.bats", 'echo "@test \\\"string\\\" { true; }"\n'),
        ("decoy.bats", '@test "unterminated" {\n  true\n'),
        ("decoy.bats", '@test "empty" {\n  # decoy\n}\n'),
        ("decoy.bats", "decoy\n"),
    ],
)
def test_invalid_non_executable_runner_sources_are_phantoms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, contents: str
) -> None:
    """Suffixes, comments, strings, and substrings cannot establish a runner contract."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    write_runner_source(repo / filename, contents)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("decoy", {"file": filename, "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1


def test_runner_source_predicate_rejects_suffix_and_substring_only_mutants(tmp_path: Path) -> None:
    """Mutation evidence: neither an allowed suffix nor a test substring is sufficient."""
    suffix_only = tmp_path / "test_suffix.py"
    substring_only = tmp_path / "not_a_test.txt"
    write_runner_source(suffix_only, "decoy\n")
    write_runner_source(substring_only, "def test_but_wrong_suffix():\n    assert True\n")

    assert not MODULE._is_runner_managed_test_source(suffix_only)
    assert not MODULE._is_runner_managed_test_source(substring_only)


def test_javascript_invalid_template_interpolation_is_rejected(tmp_path: Path) -> None:
    """Acorn syntax, not a template-oblivious lexer, decides whole-file validity."""
    source = tmp_path / "invalid-template.test.js"
    write_runner_source(source, 'test("ok", () => { const x = `${foo(}`; });')

    assert not MODULE._is_runner_managed_test_source(source)


def test_javascript_regex_literal_cannot_impersonate_test_call(tmp_path: Path) -> None:
    """Syntactically valid regex data is not a JavaScript call expression."""
    source = tmp_path / "regex-decoy.test.js"
    write_runner_source(source, 'const re = /test("x", () => {})/;\n')

    assert not MODULE._is_runner_managed_test_source(source)


def test_javascript_for_of_regex_cannot_impersonate_test_call(tmp_path: Path) -> None:
    """Contextual keywords cannot expose regex contents to candidate scanning."""
    source = tmp_path / "for-of-regex-decoy.test.js"
    write_runner_source(source, 'for (const x of /test("x", () => {})/) {}\n')

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        '<!-- test("x", () => {})\n',
        '--> test("x", () => {})\n',
        '#! test("x", () => {})\n',
    ],
    ids=["html-open-comment", "html-close-comment", "hashbang"],
)
def test_javascript_line_comment_forms_cannot_impersonate_test_call(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "line-comment-decoy.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


def test_javascript_nested_template_data_cannot_impersonate_test_call(tmp_path: Path) -> None:
    """Nested template literal text must stay outside candidate scanning."""
    source = tmp_path / "nested-template-decoy.test.js"
    write_runner_source(source, 'const value = `${`test("x", () => {})`}`;\n')

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        (
            "class C { #test(name, body) {} "
            'run() { this.#test("x", () => {}); } }\n'
        ),
        'class test {}\nnew test("x", () => {});\n',
    ],
    ids=["private-method", "constructor"],
)
def test_javascript_non_bare_test_invocations_are_rejected(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "non-bare.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'const x=6 / 2; test("ok",()=>{});\n',
        'const a=`a`; test("ok",()=>{}); const b=`b`;\n',
        'test /* call-site trivia */ ("ok",()=>{});\n',
    ],
    ids=["division-before-test", "templates-around-test", "comment-before-call"],
)
def test_javascript_parser_oracle_accepts_valid_slash_and_template_source(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "parser-oracle.test.js"
    write_runner_source(source, contents)

    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'const value = "test( data";\n',
        "// test( data\nconst value = 1;\n",
        "/* test( data */ const value = 1;\n",
        "const value = `test( data`;\n",
        "const value = /test\\( data/;\n",
    ],
    ids=["string", "line-comment", "block-comment", "template-raw", "regex"],
)
def test_javascript_parser_oracle_rejects_test_candidates_in_data(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "data-decoy.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


def test_javascript_parser_oracle_accepts_test_in_template_interpolation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "template-interpolation.test.js"
    write_runner_source(source, 'const value = `${test("ok",()=>{})}`;\n')

    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        "test();\n",
        "test(123);\n",
        'test("name");\n',
        'test("name", 123);\n',
        'test("name", callback);\n',
        'test("name", () => {}, "extra");\n',
        'test("name", function () {}, "extra");\n',
        'test("name", function () {}, injected = 1);\n',
        'test("name", () => {}, {injected} = obj);\n',
        'const test=(x)=>x; test("not a runner test");\n',
    ],
    ids=[
        "missing-arguments",
        "non-name-only-argument",
        "missing-callback",
        "number-callback",
        "callback-reference",
        "extra-arrow-argument",
        "extra-function-argument",
        "extra-assignment-argument",
        "extra-destructuring-argument",
        "review-decoy",
    ],
)
def test_javascript_runner_call_requires_name_and_inline_callable(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "call-shape-decoy.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'const test = (name, body) => body; test("name", () => {});\n',
        'let test; test("name", () => {});\n',
        'var test = () => {}; test("name", () => {});\n',
        'function wrapper(test) { test("name", () => {}); }\n',
        'import { runnerTest as test } from "runner"; test("name", () => {});\n',
        'function test(name, body) {} test("name", () => {});\n',
    ],
    ids=["const", "let", "var", "parameter", "import-alias", "function"],
)
def test_javascript_shadowed_test_identifier_is_not_runner_managed(
    tmp_path: Path, contents: str
) -> None:
    if contents.startswith("import "):
        (tmp_path / "package.json").write_text(
            '{"type":"module"}\n', encoding="utf-8"
        )
    source = tmp_path / "shadowed.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'const { test } = { test: (name, body) => 0 }; test("fake",()=>{});\n',
        'const { test } = require("fake"); test("fake",()=>{});\n',
        'try {} catch (test) { test("fake",()=>{}); }\n',
        'class X { m(test) { test("fake",()=>{}); } }\n',
    ],
    ids=["destructuring-literal", "destructuring-require", "catch", "method-parameter"],
)
def test_javascript_all_bare_test_bindings_are_rejected(
    tmp_path: Path, contents: str
) -> None:
    """Any additional code-level bare ``test`` is a conservative shadow."""
    source = tmp_path / "shadowed-binding.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        (
            "const { test, assert, eq } = global.__ff\n"
            'test("trusted", () => {});\n'
        ),
        (
            "const{test,assert,eq}=global.__ff;\n"
            'test("trusted", async function () {});\n'
        ),
    ],
    ids=["live-spacing", "compact-spacing"],
)
def test_javascript_trusted_global_ff_binding_is_runner_managed(
    tmp_path: Path, contents: str
) -> None:
    """Fleet's exact immutable runner binding may supply genuine test calls."""
    source = tmp_path / "global-ff.test.js"
    write_runner_source(source, contents)

    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "prologue",
    [
        "",
        "  /* runner prelude */\n// binding follows\n",
        "'use strict'\n",
        '"use strict"; /* runner prelude */\n',
    ],
    ids=["empty", "comments", "single-quoted-strict", "double-quoted-strict"],
)
def test_javascript_global_ff_binding_allows_only_the_runner_prologue(
    tmp_path: Path, prologue: str
) -> None:
    source = tmp_path / "global-ff-prologue.test.js"
    write_runner_source(
        source,
        f"{prologue}const {{ test, assert, eq }} = global.__ff; "
        'test("trusted",()=>{});\n',
    )

    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "mutation",
    [
        "global.__ff = {test:(name,body)=>0,assert:0,eq:0}; ",
        (
            'Object.defineProperty(global,"__ff",'
            "{value:{test:(name,body)=>0,assert:0,eq:0}}); "
        ),
        "const alias = global; alias.__ff = {test:(name,body)=>0,assert:0,eq:0}; ",
        (
            'const key = "__" + "ff"; global[key] = '
            "{test:(name,body)=>0,assert:0,eq:0}; "
        ),
    ],
    ids=["direct-assignment", "define-property", "alias", "computed-built-key"],
)
def test_javascript_global_ff_prebinding_mutations_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    """Candidate code cannot replace the runner object before it is read."""
    source = tmp_path / "global-ff-prebinding-mutation.test.js"
    write_runner_source(
        source,
        f"{mutation}const {{ test, assert, eq }} = global.__ff; "
        'test("fake",()=>{});\n',
    )

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "prologue",
    [
        "0; ",
        "const harmless = 0; ",
        '"another directive"; ',
        'import "runner-setup"; ',
    ],
    ids=["expression", "declaration", "other-directive", "import"],
)
def test_javascript_global_ff_binding_rejects_other_executable_prologues(
    tmp_path: Path, prologue: str
) -> None:
    source = tmp_path / "global-ff-executable-prologue.test.js"
    write_runner_source(
        source,
        f"{prologue}const {{ test, assert, eq }} = global.__ff; "
        'test("fake",()=>{});\n',
    )

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'const { test, assert, eq } = local.__ff; test("fake",()=>{});\n',
        'const { test, assert, eq } = global.fake; test("fake",()=>{});\n',
        'const { test, assert, eq } = global["__ff"]; test("fake",()=>{});\n',
        'const { test, assert, eq } = global.__ff.fake; test("fake",()=>{});\n',
        'const { test, assert, eq } = global.__ff || local; test("fake",()=>{});\n',
        'const { assert, test, eq } = global.__ff; test("fake",()=>{});\n',
        'const { test, assert, eq, extra } = global.__ff; test("fake",()=>{});\n',
        'const { test: alias, assert, eq } = global.__ff; alias("fake",()=>{});\n',
        'const { test: test, assert, eq } = global.__ff; test("fake",()=>{});\n',
        'const { test, assert, eq } = global.__ff;\n',
        'const { test, assert, eq } = global.__ff; test("inert");\n',
        (
            'if (false) { const { test, assert, eq } = global.__ff; '
            'test("inert",()=>{}); }\n'
        ),
        (
            'function inert() { const { test, assert, eq } = global.__ff; '
            'test("inert",()=>{}); }\n'
        ),
        (
            'for (; false;) { const { test, assert, eq } = global.__ff; '
            'test("inert",()=>{}); }\n'
        ),
        (
            'const { test, assert, eq } = global.__ff; '
            'if (false) test("inert",()=>{});\n'
        ),
        (
            'const { test, assert, eq } = global.__ff; '
            'function inert() { test("inert",()=>{}); }\n'
        ),
        (
            'const { test, assert, eq } = global.__ff; '
            'false && test("inert",()=>{});\n'
        ),
        (
            'const { test, assert, eq } = global.__ff; test = local; '
            'test("fake",()=>{});\n'
        ),
        (
            'let { test, assert, eq } = global.__ff; test = local; '
            'test("fake",()=>{});\n'
        ),
        (
            'const { test, assert, eq } = global.__ff; '
            '({test} = local); test("fake",()=>{});\n'
        ),
    ],
    ids=[
        "local-object",
        "wrong-global-property",
        "computed-source",
        "chained-source",
        "fallback-source",
        "member-order",
        "extra-member",
        "different-local-alias",
        "explicit-test-alias",
        "missing-call",
        "malformed-call",
        "unreachable-branch-binding",
        "uncalled-function-binding",
        "zero-iteration-binding",
        "top-level-binding-unreachable-call",
        "top-level-binding-uncalled-function",
        "top-level-binding-short-circuit-call",
        "later-reassignment",
        "mutable-declaration",
        "later-destructuring-mutation",
    ],
)
def test_javascript_global_ff_near_neighbors_are_rejected(
    tmp_path: Path, contents: str
) -> None:
    """Only the exact immutable Fleet binding is trusted; close decoys fail."""
    source = tmp_path / "global-ff-decoy.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'const \\u0074est = (name, body) => 0; test("fake",()=>{});\n',
        'const {...test} = obj; test("fake",()=>{});\n',
        'new test("fake",()=>{});\n',
        'globalThis.test = (name, body) => 0; test("fake",()=>{});\n',
        'globalThis.test ||= (name, body) => 0; test("fake",()=>{});\n',
        'globalThis.test &&= (name, body) => 0; test("fake",()=>{});\n',
        'globalThis.test ??= (name, body) => 0; test("fake",()=>{});\n',
        'const alias = globalThis; alias.test = (name, body) => 0; test("fake",()=>{});\n',
        'const key = "test"; globalThis[key] = (name, body) => 0; test("fake",()=>{});\n',
        (
            'const alias = globalThis; Object.defineProperty(alias,"test",'
            '{value:(name,body)=>0}); test("fake",()=>{});\n'
        ),
        '[globalThis.test] = [(name, body) => 0]; test("fake",()=>{});\n',
        '({test:globalThis.test}={test:(name, body)=>0}); test("fake",()=>{});\n',
        'for (globalThis.test of [(name, body)=>0]) {} test("fake",()=>{});\n',
        'delete globalThis.test; test("fake",()=>{});\n',
        'delete globalThis?.test; test("fake",()=>{});\n',
        'delete (globalThis.test); test("fake",()=>{});\n',
        'delete (0, globalThis.test); test("fake",()=>{});\n',
        'with ({test:(name, body)=>0}) { test("fake",()=>{}); }\n',
    ],
    ids=[
        "unicode-escaped-binding",
        "rest-binding",
        "constructor-call",
        "member-assignment",
        "member-logical-or-assignment",
        "member-logical-and-assignment",
        "member-nullish-assignment",
        "aliased-member-assignment",
        "computed-member-assignment",
        "aliased-define-property",
        "member-array-target",
        "member-object-target",
        "member-for-of-target",
        "member-delete",
        "member-optional-delete",
        "member-parenthesized-delete",
        "member-sequence-delete",
        "with-binding",
    ],
)
def test_javascript_shadow_variants_and_non_runner_calls_are_rejected(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "shadow-variant.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        (
            'const alias=globalThis; const key="test"; '
            'alias[key]=(n,b)=>0; test("fake",()=>{});\n'
        ),
        (
            'const alias=globalThis; const key="test"; '
            'Reflect.set(alias,key,(n,b)=>0); test("fake",()=>{});\n'
        ),
        (
            'const alias=globalThis; const payload={test:(n,b)=>0}; '
            'Object.assign(alias,payload); test("fake",()=>{});\n'
        ),
        'const alias = global; test("fake",()=>{});\n',
        'const first = globalThis; const second = first; test("fake",()=>{});\n',
        'let alias; alias = globalThis; test("fake",()=>{});\n',
        'const {globalThis: alias} = globalThis; test("fake",()=>{});\n',
        'let alias; ({global: alias} = global); test("fake",()=>{});\n',
        (
            'const alias=globalThis; const key="te" + "st"; '
            'Reflect.set(alias,key,(n,b)=>0); test("fake",()=>{});\n'
        ),
        (
            'const alias=globalThis; Object.defineProperty(alias,key,{value: runner}); '
            'test("fake",()=>{});\n'
        ),
        (
            'const alias=global; Object.defineProperties(alias,payload); '
            'test("fake",()=>{});\n'
        ),
        (
            'const alias=globalThis; Reflect.defineProperty(alias,key,descriptor); '
            'test("fake",()=>{});\n'
        ),
        'Reflect.set(globalThis,key,runner); test("fake",()=>{});\n',
        'Object.assign(global,payload); test("fake",()=>{});\n',
        'Object.defineProperty(globalThis,key,descriptor); test("fake",()=>{});\n',
        'Object.defineProperties(global,payload); test("fake",()=>{});\n',
        'Reflect.defineProperty(globalThis,key,descriptor); test("fake",()=>{});\n',
    ],
    ids=[
        "required-computed-assignment",
        "required-reflect-set",
        "required-object-assign",
        "global-alias-binding",
        "alias-chain",
        "assignment-alias",
        "destructured-global-this-alias",
        "destructured-global-assignment-alias",
        "computed-key-construction",
        "object-define-property-unknown-key",
        "object-define-properties-unknown-payload",
        "reflect-define-property-unknown-key",
        "direct-reflect-set-unknown-key",
        "direct-object-assign-unknown-payload",
        "direct-object-define-property-unknown-key",
        "direct-object-define-properties-unknown-payload",
        "direct-reflect-define-property-unknown-key",
    ],
)
def test_javascript_global_alias_flows_and_mutation_apis_are_rejected(
    tmp_path: Path, contents: str
) -> None:
    """Candidate code cannot retain or mutate the process-global object."""
    source = tmp_path / "global-alias-flow.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'const alias = "global"; test("real",()=>{});\n',
        'const alias = "global" + "This"; test("real",()=>{});\n',
        'const alias = holder["global" + "This"]; test("real",()=>{});\n',
        'Reflect.set(local, "te" + "st", runner); test("real",()=>{});\n',
        'Object.assign(local, payload); test("real",()=>{});\n',
        'Object.defineProperty(local, key, descriptor); test("real",()=>{});\n',
        'Object.defineProperties(local, payload); test("real",()=>{});\n',
        'Reflect.defineProperty(local, key, descriptor); test("real",()=>{});\n',
    ],
    ids=[
        "global-string",
        "constructed-global-this-string",
        "computed-local-member",
        "local-reflect-set",
        "local-object-assign",
        "local-object-define-property",
        "local-object-define-properties",
        "local-reflect-define-property",
    ],
)
def test_javascript_global_alias_near_neighbors_remain_runner_managed(
    tmp_path: Path, contents: str
) -> None:
    """Textual lookalikes and mutations of local objects are not global aliases."""
    source = tmp_path / "global-alias-neighbor.test.js"
    write_runner_source(source, contents)

    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'test("arrow", () => {});\n',
        'test(`template ${name}`, async () => {});\n',
        'test("function", function () {});\n',
        'test("async function", async function () {});\n',
    ],
    ids=["arrow", "async-arrow-template", "function", "async-function"],
)
def test_javascript_runner_call_accepts_supported_inline_callbacks(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "supported-callback.test.js"
    write_runner_source(source, contents)

    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "contents",
    [
        'test("regex block", () => { expect(/}/.test("}")); });\n',
        'test("expression arrow", () => expect(1).toBe(1));\n',
        'test("first", () => {}); test("second", async () => 2);\n',
        'test("compact async", async()=>{});\n',
        'test("commented async", async /* trivia */ () => {});\n',
        'test("regex paren", function () { expect(/\\)/.test(")")); });\n',
    ],
    ids=[
        "regex-in-block",
        "expression-bodied-arrow",
        "multiple-global-calls",
        "compact-async-arrow",
        "commented-async-arrow",
        "regex-paren-function",
    ],
)
def test_javascript_parser_oracle_accepts_required_runner_shapes(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "required-shape.test.js"
    write_runner_source(source, contents)

    assert MODULE._is_runner_managed_test_source(source)


def test_javascript_candidate_bound_allows_256_global_calls(tmp_path: Path) -> None:
    """The runner-call ceiling is reachable by legitimate runner calls."""
    source = tmp_path / "candidate-bound.test.js"
    write_runner_source(
        source,
        "".join(f'test("{index}",()=>{{}});\n' for index in range(256)),
    )

    assert MODULE._is_runner_managed_test_source(source)


def test_javascript_large_256_call_source_completes_with_one_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A large valid boundary source must not regress to per-candidate parsing."""
    source = tmp_path / "large-boundary.test.js"
    write_runner_source(
        source,
        "const payload = " + repr("x" * 28_000) + ";\n"
        + "".join(f'test("{index}",()=>{{ void payload; }});\n' for index in range(256)),
    )
    real_run = subprocess.run
    node_calls = 0

    def count_node(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal node_calls
        if argv and argv[0] == "node":
            node_calls += 1
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", count_node)
    started = time.monotonic()

    assert MODULE._is_runner_managed_test_source(source)
    assert time.monotonic() - started < 2.0
    assert node_calls == 1


def test_live_fleet_javascript_source_classifies_true_and_is_byte_identical() -> None:
    """Exercise the exact 28 KiB Fleet source when that checkout is present."""
    source = Path("/home/psimmons/projects/fleet/orchestration/test/adversarial-loop.test.js")
    if not source.is_file():
        pytest.skip("live Fleet checkout is not present")
    before = source.read_bytes()

    assert MODULE._is_runner_managed_test_source(source)
    assert source.read_bytes() == before


def test_duplicate_javascript_references_parse_once_per_verifier_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    source = repo / "duplicate.test.js"
    write_runner_source(source, 'test("one",()=>{});\n')
    write_records(
        l1_dir,
        "sample",
        machine_record("first", {"file": source.name, "kind": "test"}),
        machine_record("second", {"file": source.name, "kind": "test"}),
    )
    real_run = subprocess.run
    node_calls = 0

    def count_node(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal node_calls
        if argv and argv[0] == "node":
            node_calls += 1
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", count_node)

    report = MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})

    assert not report.phantoms
    assert node_calls == 1


def test_javascript_runner_source_is_never_executed(tmp_path: Path) -> None:
    sentinel = tmp_path / "javascript-executed"
    source = tmp_path / "inert.test.js"
    write_runner_source(
        source,
        f'require("fs").writeFileSync("{sentinel}", "executed");\n'
        'test("name", () => {});\n',
    )

    assert MODULE._is_runner_managed_test_source(source)
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "contents",
    [
        "function test() {}\n",
        'const suite = {test() {}}; suite.test("ok",()=>{});\n',
        'const suite = {}; suite /* a */ . /* b */ test("ok",()=>{});\n',
        "const saved = test;\n",
        "const \u03c0test = () => {}; \u03c0test();\n",
    ],
    ids=[
        "function-declaration",
        "property-call",
        "commented-property-call",
        "bare-reference",
        "unicode-identifier",
    ],
)
def test_javascript_non_call_contexts_do_not_count(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "context-decoy.test.js"
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


def test_bats_top_level_commands_are_never_executed(tmp_path: Path) -> None:
    sentinel = tmp_path / "top-level-executed"
    source = tmp_path / "top-level.bats"
    write_runner_source(
        source,
        f'touch "{sentinel}"\n@test "ok" {{ true; }}\n',
    )

    assert MODULE._is_runner_managed_test_source(source)
    assert not sentinel.exists()


def test_bats_test_body_commands_are_never_executed(tmp_path: Path) -> None:
    sentinel = tmp_path / "body-executed"
    source = tmp_path / "body.bats"
    write_runner_source(
        source,
        f'@test "ok" {{ touch "{sentinel}"; }}\n',
    )

    assert MODULE._is_runner_managed_test_source(source)
    assert not sentinel.exists()


def test_bats_heredoc_data_is_counted_without_executing_test_body(
    tmp_path: Path,
) -> None:
    """A literal closing brace in heredoc data is valid and remains inert."""
    sentinel = tmp_path / "body-executed"
    source = tmp_path / "heredoc.bats"
    write_runner_source(
        source,
        (
            '@test "heredoc data" {\n'
            "  cat <<'HEREDOC'\n"
            "}\n"
            "HEREDOC\n"
            f'  touch "{sentinel}"\n'
            "}\n"
        ),
    )

    assert MODULE._is_runner_managed_test_source(source)
    assert not sentinel.exists()


def test_bats_heredoc_test_text_is_not_a_declaration(tmp_path: Path) -> None:
    source = tmp_path / "heredoc-decoy.bats"
    write_runner_source(
        source,
        "cat <<'HEREDOC'\n@test \"fake\" { true; }\nHEREDOC\n",
    )

    assert not MODULE._is_runner_managed_test_source(source)


def test_bats_missing_preprocessor_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "missing-preprocessor.bats"
    write_runner_source(source, '@test "ok" { true; }\n')
    monkeypatch.setattr(shutil, "which", lambda executable: None)

    assert not MODULE._is_runner_managed_test_source(source)


def test_bats_missing_bash_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "missing-bash.bats"
    write_runner_source(source, '@test "ok" { true; }\n')
    real_run = subprocess.run

    def fail_bash(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if argv[0] == "bash":
            raise FileNotFoundError("bash missing")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_bash)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "bash_failure",
    [
        subprocess.CompletedProcess(["bash", "-n"], 2, "", "invalid"),
        subprocess.TimeoutExpired(cmd=["bash", "-n"], timeout=5),
        OSError("bash failed"),
    ],
    ids=["syntax-failure", "timeout", "os-error"],
)
def test_bats_bash_validation_failure_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bash_failure: subprocess.CompletedProcess[str]
    | subprocess.TimeoutExpired
    | OSError,
) -> None:
    source = tmp_path / "bash-failure.bats"
    write_runner_source(source, '@test "ok" { true; }\n')
    real_run = subprocess.run

    def fail_bash(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if argv == ["bash", "-n"]:
            if isinstance(bash_failure, BaseException):
                raise bash_failure
            return bash_failure
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_bash)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "runner_error",
    [
        subprocess.TimeoutExpired(cmd=["node", "--check", "-"], timeout=5),
        OSError("node failed"),
    ],
    ids=["timeout", "os-error"],
)
def test_javascript_parser_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_error: subprocess.TimeoutExpired | OSError,
) -> None:
    source = tmp_path / "probe-error.test.js"
    write_runner_source(source, 'test("ok",()=>{});\n')
    real_run = subprocess.run

    def fail_probe(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if argv == MODULE.JAVASCRIPT_ACORN_ARGV:
            raise runner_error
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_probe)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "true",
        '{"managed":true,"extra":false}',
        "not-json",
        '{"managed":true}' + (" " * MODULE.MAX_JAVASCRIPT_PARSER_OUTPUT_BYTES),
    ],
    ids=["empty", "wrong-shape", "extra-field", "invalid-json", "oversized"],
)
def test_javascript_malformed_parser_output_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    source = tmp_path / "malformed-parser-output.test.js"
    write_runner_source(source, 'test("ok",()=>{});\n')
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout, ""),
    )

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        (
            "too-many.test.js",
            "".join(
                f'test("{index}",()=>{{}});\n'
                for index in range(MODULE.MAX_RUNNER_CANDIDATES + 1)
            ),
        ),
        (
            "too-many.bats",
            '@test "bounded" { true; }\n' * (MODULE.MAX_RUNNER_CANDIDATES + 1),
        ),
        (
            "too-many-bindings.test.js",
            ("{ const test = null; }\n" * (MODULE.MAX_RUNNER_CANDIDATES + 1))
            + 'test("real",()=>{});\n',
        ),
    ],
)
def test_runner_candidate_limit_fails_closed(
    tmp_path: Path, filename: str, contents: str
) -> None:
    source = tmp_path / filename
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("missing.test.js", 'test("ok", () => {});\n'),
        ("missing.bats", '@test "ok" { true; }\n'),
    ],
)
@pytest.mark.parametrize(
    "runner_error",
    [
        FileNotFoundError("runner missing"),
        PermissionError("runner not executable"),
        subprocess.TimeoutExpired(cmd=["runner"], timeout=5),
    ],
    ids=["missing-executable", "os-error", "timeout"],
)
def test_runner_invocation_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    contents: str,
    runner_error: OSError | subprocess.TimeoutExpired,
) -> None:
    source = tmp_path / filename
    write_runner_source(source, contents)

    def fail_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise runner_error

    monkeypatch.setattr(subprocess, "run", fail_run)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents", "stdout"),
    [
        ("failed.test.js", 'test("ok", () => {});\n', ""),
        ("failed.bats", '@test "ok" { true; }\n', "1\n"),
    ],
)
def test_runner_nonzero_exit_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    contents: str,
    stdout: str,
) -> None:
    source = tmp_path / filename
    write_runner_source(source, contents)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout, "parse failed"),
    )

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    "stdout", ["", "echo no-tests\n", ")\n", None]
)
def test_bats_invalid_or_empty_preprocessor_output_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str | None,
) -> None:
    source = tmp_path / "malformed-preprocessor.bats"
    write_runner_source(source, '@test "ok" { true; }\n')
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout, ""),
    )

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        (
            "runner; touch PWNED $(echo x).test.js",
            'test("ok", () => {});\n',
        ),
        (
            "runner; touch PWNED $(echo x).bats",
            '@test "ok" { true; }\n',
        ),
    ],
)
def test_runner_source_path_is_one_argv_element_without_a_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    contents: str,
) -> None:
    source = tmp_path / filename
    write_runner_source(source, contents)
    calls: list[tuple[list[str], dict[str, object]]] = []
    real_run = subprocess.run

    def record_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", record_run)

    assert MODULE._is_runner_managed_test_source(source)
    if filename.endswith(".test.js"):
        assert len(calls) == 1
        argv, kwargs = calls[0]
        assert argv == MODULE.JAVASCRIPT_ACORN_ARGV
        assert kwargs["input"] == contents
        assert all(str(source) not in argument for argument in argv)
    else:
        path_calls = [(argv, kwargs) for argv, kwargs in calls if str(source) in argv]
        assert len(path_calls) == 1
        argv, _ = path_calls[0]
        assert Path(argv[0]).name == "bats-preprocess"
        assert argv[1:] == [str(source)]
        assert all(Path(call[0][0]).name != "bats" for call in calls)
    for call_argv, kwargs in calls:
        assert isinstance(call_argv, list)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert 0 < kwargs["timeout"] <= 10
        assert kwargs.get("shell", False) is False


@pytest.mark.parametrize(
    ("filename", "contents", "replacement", "stdout"),
    [
        (
            "changed.test.js",
            'test("ok", () => {});\n',
            'test("broken", () =>',
            "",
        ),
        (
            "changed.bats",
            '@test "ok" { true; }\n',
            "echo no-tests-remain\n",
            "1\n",
        ),
    ],
)
def test_source_change_during_runner_parse_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    contents: str,
    replacement: str,
    stdout: str,
) -> None:
    """A runner result must not certify different bytes at the same path."""
    source = tmp_path / filename
    write_runner_source(source, contents)

    def replace_during_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_runner_source(source, replacement)
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", replace_during_run)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents", "replacement", "stdout"),
    [
        (
            "aba.test.js",
            'test("ok", () => {});\n',
            'test("broken", () =>',
            "",
        ),
        (
            "aba.bats",
            '@test "ok" { true; }\n',
            "echo no-tests-remain\n",
            "1\n",
        ),
    ],
)
def test_source_aba_change_during_runner_parse_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    contents: str,
    replacement: str,
    stdout: str,
) -> None:
    """Restoring the original bytes cannot hide an intervening source change."""
    source = tmp_path / filename
    write_runner_source(source, contents)

    def replace_and_restore(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_runner_source(source, replacement)
        write_runner_source(source, contents)
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", replace_and_restore)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents", "invalid"),
    [
        ("repeat.test.js", 'test("ok", () => {});\n', 'test("broken", () =>\n'),
        ("repeat.bats", '@test "ok" { true; }\n', "echo no-tests-remain\n"),
    ],
)
def test_runner_validation_is_fresh_on_repeat_invocation(
    tmp_path: Path,
    filename: str,
    contents: str,
    invalid: str,
) -> None:
    source = tmp_path / filename

    write_runner_source(source, invalid)
    assert not MODULE._is_runner_managed_test_source(source)
    write_runner_source(source, contents)
    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("ordinary.test.js", "#!/bin/sh\nexit 0\n"),
        ("ordinary.bats", "#!/bin/sh\nexit 0\n"),
    ],
)
def test_executable_test_file_does_not_invoke_runner_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    contents: str,
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    source = repo / filename
    source.write_text(contents, encoding="utf-8")
    source.chmod(0o755)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("ordinary", {"file": filename, "kind": "test"}),
    )

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary executable tests must not invoke a language runner")
        ),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("extra-paren.bats", '@test "ok" { true; }\n)\n'),
        ("unclosed-paren.bats", '@test "ok" { true; }\necho (\n'),
        ("unclosed-quote.bats", '@test "ok" { true; }\necho "unterminated\n'),
        ("malformed-second.bats", '@test "ok" { true; }\n@test "broken" nope\n'),
        ("extra-paren.test.js", 'test("ok", () => {}); )'),
        ("extra-bracket.test.js", 'test("ok", () => {}); ]'),
        ("unclosed-paren.test.js", 'test("ok", () => {}); ('),
        ("unclosed-brace.test.js", 'test("ok", () => {}); {'),
        ("unclosed-bracket.test.js", 'test("ok", () => {}); ['),
        ("unclosed-block-comment.test.js", 'test("ok", () => {}); /* unterminated'),
        ("unclosed-quote.test.js", 'test("ok", () => {}); "unterminated'),
        ("unclosed-template.test.js", 'test("ok", () => {}); `unterminated'),
        ("malformed-second.test.js", 'test("ok", () => {}); test("broken", () =>);'),
    ],
)
def test_valid_runner_test_prefix_does_not_hide_invalid_suffix(
    tmp_path: Path, filename: str, contents: str
) -> None:
    """A candidate is evidence only when the bounded whole file is valid."""
    source = tmp_path / filename
    write_runner_source(source, contents)

    assert not MODULE._is_runner_managed_test_source(source)


def test_bats_valid_prefix_does_not_hide_invalid_suffix(tmp_path: Path) -> None:
    source = tmp_path / "valid-prefix.bats"
    write_runner_source(source, '@test "ok" { true; }\n}\n')

    assert not MODULE._is_runner_managed_test_source(source)


def test_javascript_valid_prefix_does_not_hide_invalid_suffix(tmp_path: Path) -> None:
    source = tmp_path / "valid-prefix.test.js"
    write_runner_source(source, 'test("ok", () => {}); }')

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize("shell_word", ["{", "["])
def test_bats_authoritative_parser_accepts_delimiter_like_shell_words(
    tmp_path: Path, shell_word: str
) -> None:
    """The removed delimiter lexer rejected these valid ordinary arguments."""
    source = tmp_path / "shell-word.bats"
    write_runner_source(source, f'@test "ok" {{ true; }}\necho {shell_word}\n')

    assert MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        (
            "multiple.bats",
            (
                "setup() { true; }\n"
                '@test "first" { true; }\n'
                '@test "second" { run true; }\n'
                "teardown() { true; }\n"
                "echo '}])'\n"
                "# harmless trailing comment with ({["
            ),
        ),
        (
            "multiple.test.js",
            (
                "const before = [1];\n"
                r"const delimiters = /[)}\]]/;" "\n"
                'test("first", () => {});\n'
                'test("second", async () => { const nested = {}; });\n'
                'const text = "}])"; /* harmless unmatched-looking ({[ */\n'
                "/ok/.test(text);\n"
                "const after = {ok: true}; // harmless trailing statement and comment"
            ),
        ),
    ],
)
def test_whole_file_runner_scan_retains_multiple_tests_and_harmless_trailing_source(
    tmp_path: Path, filename: str, contents: str
) -> None:
    """Scanning to EOF must retain ordinary multi-test runner sources."""
    source = tmp_path / filename
    write_runner_source(source, contents)

    assert MODULE._is_runner_managed_test_source(source)


def test_javascript_runner_source_with_invalid_utf8_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "invalid-utf8.test.js"
    source.write_bytes(b'test("ok", () => {});\n\xff')
    source.chmod(0o664)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize("read_error", [PermissionError("denied"), FileNotFoundError("vanished")])
def test_javascript_runner_source_read_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    read_error: OSError,
) -> None:
    source = tmp_path / "read-error.test.js"
    write_runner_source(source, 'test("ok", () => {});\n')
    real_open = MODULE.os.open

    def fail_target_open(path: Path, *args: object, **kwargs: object) -> int:
        if Path(path) == source:
            raise read_error
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(MODULE.os, "open", fail_target_open)

    assert not MODULE._is_runner_managed_test_source(source)


@pytest.mark.parametrize("suffix", [".test.js", ".bats"])
def test_non_regular_fifo_runner_source_fails_closed_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    source = tmp_path / f"blocking{suffix}"
    MODULE.os.mkfifo(source)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("non-regular source must not invoke a language runner")
        ),
    )
    results: list[bool] = []
    worker = threading.Thread(
        target=lambda: results.append(MODULE._is_runner_managed_test_source(source)),
        daemon=True,
    )

    worker.start()
    worker.join(timeout=0.5)

    assert not worker.is_alive(), "regular-file check blocked while opening a FIFO"
    assert results == [False]


def test_runner_plausibility_uses_stat_not_a_separate_exists_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Containment-to-plausibility must not have an exists/stat TOCTOU split."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    source = repo / "feature.test.js"
    write_runner_source(source, 'test("ok", () => {});\n')
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("runner-test", {"file": "feature.test.js", "kind": "test"}),
    )
    real_exists = Path.exists

    def reject_target_exists(path: Path) -> bool:
        if path == source:
            raise AssertionError("enforcement path must not be checked with exists() before stat/read")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", reject_target_exists)

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    assert "phantom:" not in capsys.readouterr().err


def test_runner_source_stat_error_is_a_phantom_not_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Disappearance at metadata inspection fails closed inside the verifier."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    source = repo / "vanished.test.js"
    write_runner_source(source, 'test("ok", () => {});\n')
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("runner-test", {"file": "vanished.test.js", "kind": "test"}),
    )
    real_stat = Path.stat

    def fail_target_stat(path: Path, *args: object, **kwargs: object) -> object:
        if path == source:
            raise FileNotFoundError("vanished during metadata inspection")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_target_stat)

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    assert "phantom: vanished.test.js (sample:runner-test," in capsys.readouterr().err


@pytest.mark.parametrize(
    "contents",
    ["test(", "// test(\n", 'test("x",,)', 'test("x", function)', 'test("x", () =>)', 'test("x", () =>;)', 'test("x", () => {)'],
)
def test_invalid_or_commented_runner_test_stub_is_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str
) -> None:
    """A filename and substring alone are not evidence of a runnable test."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    repo = projects / "repo"
    repo.mkdir(parents=True)
    (repo / "decoy.test.js").write_text(contents, encoding="utf-8")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("decoy", {"file": "decoy.test.js", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1


def test_escaping_runner_managed_test_path_is_rejected_before_plausibility_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Containment must gate the content probe for an escaped test path."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "outside.test.js").write_text("test('outside', () => {});\n", encoding="utf-8")
    (projects / "repo").mkdir()
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("escape", {"file": "../outside.test.js", "kind": "test"}),
    )

    monkeypatch.setattr(
        MODULE,
        "_is_runner_managed_test_source",
        lambda path: (_ for _ in ()).throw(AssertionError(f"must not inspect {path}")),
    )
    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    assert "phantom: ../outside.test.js (sample:escape," in capsys.readouterr().err


# ---------------------------------------------------------------------------
# UNVERIFIABLE: two distinct reasons, neither counted as enforced (silent pass).
# ---------------------------------------------------------------------------


def test_root_unknown_is_unverifiable_not_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    # A second, mapped-and-present source with a REAL checked entry, so the
    # root floor sees at least one genuinely useful root and doesn't mask
    # what we're testing here behind the SKIPPED (zero-useful-roots) path.
    (projects / "anchor-repo").mkdir(parents=True)
    write_executable(projects / "anchor-repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"anchor": "anchor-repo"})
    write_records(
        l1_dir, "anchor", machine_record("anchor-1", {"file": "control.py", "kind": "test"})
    )
    # "orphan" has NO entry in source-roots.conf at all.
    write_records(
        l1_dir, "orphan", machine_record("orphan-1", {"file": "control.py", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 0  # unverifiable is not a failure
    assert "phantom:" not in err
    # Discriminating: this exact count+message only prints when
    # unverifiable_count > 0, i.e. the UNVERIFIABLE branch actually ran and
    # appended to report.unverifiable. A bare `continue` swapped in for that
    # branch (silently treating the entry as neither checked nor flagged)
    # would leave this count at 0 and this line unprinted -- "unverifiable"
    # in err.lower() alone does NOT catch that, because the line is printed
    # unconditionally too (in the SCOPE footer, and per-source summary row).
    assert "UNVERIFIABLE: 1 enforcement-bearing entries could not be checked" in err
    # The specific detail line, keyed to the entry that was actually
    # appended -- not just the source name, which also appears in the
    # always-printed summary table regardless of whether detection ran.
    assert "unverifiable: control.py (orphan:orphan-1," in err


def test_root_known_but_directory_missing_is_unverifiable_not_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "anchor-repo").mkdir()
    write_executable(projects / "anchor-repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    # "vanished" is mapped, but its target directory does not exist on this
    # machine -- exactly the CI-runner-without-checkouts case, but scoped to
    # one source instead of all of them. "anchor" has a real, resolving
    # entry so the root floor sees a genuinely useful root.
    write_source_roots(roots_path, {"anchor": "anchor-repo", "vanished": "never-checked-out"})
    write_records(
        l1_dir, "anchor", machine_record("anchor-1", {"file": "control.py", "kind": "test"})
    )
    write_records(
        l1_dir, "vanished", machine_record("v-1", {"file": "control.py", "kind": "test"})
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "phantom:" not in err
    # Discriminating, same rationale as test_root_unknown_is_unverifiable_not_enforced.
    assert "UNVERIFIABLE: 1 enforcement-bearing entries could not be checked" in err
    assert "unverifiable: control.py (vanished:v-1," in err


# ---------------------------------------------------------------------------
# The fail-open case: nothing resolved must ERROR, never silently pass.
# ---------------------------------------------------------------------------


def test_zero_roots_resolved_is_an_error_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()  # exists, but none of the mapped repo subdirs do
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "does-not-exist-on-this-machine"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err  # must fail as an ERROR, not be misreported as a phantom
    assert "error" in err.lower()


def test_require_roots_flag_raises_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo-a").mkdir(parents=True)
    write_executable(projects / "repo-a" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"a": "repo-a", "b": "repo-b-not-checked-out"})
    # "a" has a real, resolving, non-null entry -- genuinely useful, not just
    # resolved. "b" doesn't resolve at all.
    write_records(l1_dir, "a", machine_record("a-1", {"file": "control.py", "kind": "test"}))
    write_records(l1_dir, "b", machine_record("b-1", None))

    # Only 1 of 2 mapped roots actually verified anything; demanding 2 must
    # ERROR even though nothing is phantom.
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, extra_args=["--require-roots", "2"]
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "error" in err.lower()


# ---------------------------------------------------------------------------
# The inverse of the original bug: a path that happens to exist SOMEWHERE
# under projects_dir (in a different repo) must not count as enforced just
# because it was found -- it must resolve under ITS OWN mapped root.
# ---------------------------------------------------------------------------


def test_path_existing_in_a_different_repo_is_still_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    # The file genuinely exists -- but in a sibling repo, not "sample"'s own root.
    (projects / "sibling-repo").mkdir(parents=True)
    (projects / "sibling-repo" / "control.py").touch()
    (projects / "sample-repo").mkdir(parents=True)  # sample's real root: empty
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "sample-repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    # Discriminating: the bare filename alone would also match a merely
    # UNVERIFIABLE detail line or an unrelated print; the exact phantom
    # rendering only appears when the resolve-under-own-root check actually
    # failed it.
    assert "phantom: control.py (sample:example," in capsys.readouterr().err


# ---------------------------------------------------------------------------
# SELF: the one root that must resolve in ANY environment (CI included),
# because it's this checkout's own root, not a sibling under ~/projects.
# ---------------------------------------------------------------------------


def test_self_root_token_resolves_to_this_repo_regardless_of_projects_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    # projects_dir points nowhere real -- if SELF fell back to projects_dir,
    # every entry here would be UNVERIFIABLE (or ERROR at the roots floor).
    projects = tmp_path / "does-not-exist-anywhere"
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "SELF"})
    write_records(
        l1_dir,
        "sample",
        machine_record("real", {"file": "guard/failure_mode_catalog_guard.py", "kind": "test"}),
        machine_record("fake", {"file": "guard/definitely-not-a-real-file.py", "kind": "test"}),
    )

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 1  # the fake one is a genuine (undocumented) phantom
    assert "phantom: guard/definitely-not-a-real-file.py" in err
    assert "guard/failure_mode_catalog_guard.py" not in err.replace(
        "phantom: guard/definitely-not-a-real-file.py", ""
    )  # the real one stayed silent
    # SELF resolved AND verified 2 entries -- the ROOT-FLOOR path specifically
    # must not be why this failed (it failed because the fake phantom is
    # undocumented in known-phantoms.conf, a distinct and correct gate).
    assert "refusing to report success" not in err
    assert "undocumented: phantom: guard/definitely-not-a-real-file.py" in err


# ---------------------------------------------------------------------------
# The map itself must never silently be treated as "no map, so all fine".
# ---------------------------------------------------------------------------


def test_missing_source_roots_conf_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    roots_path = tmp_path / "does-not-exist.conf"
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "source-roots" in err.lower() or "source_roots" in err.lower()


def test_empty_source_roots_conf_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    roots_path = tmp_path / "empty.conf"
    roots_path.write_text("# just a comment, no mappings\n", encoding="utf-8")
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err


# ---------------------------------------------------------------------------
# Preserved from the original two-way check.
# ---------------------------------------------------------------------------


def test_unbacked_machine_entry_warns_but_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    assert "WARNING" in capsys.readouterr().err


def test_unbacked_judgment_entry_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", {"id": "example", "auto": "judgment", "enforcement": None})

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    assert "WARNING" not in capsys.readouterr().err


def test_real_corpus_reports_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert MODULE.main(["--verify-enforcement"]) in {0, 1}
    output = capsys.readouterr().err
    assert "summary" in output.lower()
    assert "machine" in output.lower()


# ---------------------------------------------------------------------------
# The falsifiable root floor (C4c item 2): a root that RESOLVES but never
# had a single non-null entry to actually check proves nothing and must not
# satisfy --require-roots. This is exactly the CI/homelab-canon shape: SELF
# always resolves, but every one of its entries is enforcement: null.
# ---------------------------------------------------------------------------


def test_resolved_root_with_zero_checked_entries_does_not_satisfy_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)  # the root genuinely resolves...
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # ...but its only entry is unbacked, so it never actually gets checked.
    write_records(l1_dir, "sample", machine_record("example", None))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, extra_args=["--require-roots", "1"])
    err = capsys.readouterr().err
    # Must NOT be a silent/vacuous pass reported as "verified" -- and must
    # not be misreported as a phantom or a hard ERROR either: the
    # environment isn't misconfigured, it structurally has nothing to check
    # yet. A declared SKIP is the honest outcome.
    assert exit_code == 0
    assert "phantom:" not in err
    assert "SKIPPED" in err


def test_zero_roots_resolved_at_all_is_still_a_hard_error_not_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Distinguishes the two honest-failure shapes: a root that resolves but
    checks nothing is a SKIP (above); NO root resolving at all is still the
    original, harder signal that the environment itself looks broken
    (wrong projects_dir, deleted source-roots.conf mappings, ...)."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()  # exists, but the mapped subdir does not
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "does-not-exist-on-this-machine"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "SKIPPED" not in err
    assert "0 of 1 mapped source roots are present on this machine at all" in err


# ---------------------------------------------------------------------------
# The enforcement-bearing floor (C4c item 3, "floor not just a cap"): the
# fleet#152 shape -- a debt ledger can be "reduced" by deleting the flagged
# entry instead of fixing it. Only a floor on the TOTAL corpus count catches
# that, and it must hold with NO root resolved at all (root-independent).
# ---------------------------------------------------------------------------


def test_enforcement_bearing_count_dropping_below_floor_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # Only 1 enforcement-bearing entry exists this run...
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    # ...but the floor says there used to be 5 -- as if 4 records were
    # deleted (or their enforcement value nulled) instead of ever being
    # fixed. That must fail loud, even though nothing here is phantom.
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor=5
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "dropped to 1, below floor 5" in err


def test_enforcement_bearing_count_at_or_above_floor_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, enforcement_floor=1)
    assert exit_code == 0


def test_missing_enforcement_floor_file_fails_loud_not_a_silent_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        enforcement_floor_path=tmp_path / "does-not-exist-floor.conf",
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "phantom:" not in err
    assert "enforcement floor file not found" in err.lower()


def test_malformed_enforcement_floor_file_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", None))

    floor_path = tmp_path / "bad-floor.conf"
    floor_path.write_text("not-a-number\n", encoding="utf-8")
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor_path=floor_path
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "not an integer" in err.lower()


# ---------------------------------------------------------------------------
# The known-phantoms debt ledger (C4c item 3): a phantom already documented
# (with evidence + disposition) is visible debt, not a build failure -- but
# an UNDOCUMENTED phantom is fatal by default, and the ledger going missing
# must never be a silent "0 known, so nothing to check."
# ---------------------------------------------------------------------------


def test_documented_phantom_is_debt_not_a_build_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"}))

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "sample",
                "id": "example",
                "claimed_path": "missing.py",
                "evidence": "ls repo/missing.py -> absent (test fixture)",
                "disposition": "genuine-phantom: test fixture",
            }
        ],
    )
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "phantom: missing.py (sample:example," in err  # still visible, not hidden
    assert "DEBT: 1 known phantom(s)" in err


def test_undocumented_phantom_is_fatal_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)  # empty ledger
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "undocumented: phantom: missing.py (sample:example," in err
    assert "new phantoms cannot land silently" in err.lower()


def test_accept_phantom_flag_bypasses_for_this_run_only_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"}))

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, extra_args=["--accept-phantom"]
    )
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "WARNING" in err
    assert "--accept-phantom set" in err


def test_missing_known_phantoms_ledger_fails_loud_not_a_silent_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The (c) mutation bar: deleting known-phantoms.conf must go red, even
    on a corpus with zero real phantoms -- a vanished ledger must never be
    silently read as '0 known, so nothing to check.'"""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms_path=tmp_path / "does-not-exist-ledger.conf",
    )
    err = capsys.readouterr().err
    assert exit_code != 0
    assert "known-phantoms ledger not found" in err.lower()


def test_empty_known_phantoms_ledger_is_a_valid_zero_debt_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path, known_phantoms=[])
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "DEBT: 0 known phantom(s)" in err


# ---------------------------------------------------------------------------
# Mutation-sweep gap closures (lane-guard survivors S1, S2, S3, S8, S9, S11,
# S12, S13). Each test below was proven to FAIL against its named mutant and
# PASS against unmutated code -- see the sweep report for the diffs.
# ---------------------------------------------------------------------------


def test_path_escaping_its_own_root_is_phantom_even_when_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S1/M23: containment, not mere existence.

    `test_path_existing_in_a_different_repo_is_still_phantom` uses a bare
    filename that does not exist under EITHER root, so exists() alone already
    fails it -- it cannot discriminate the `is_relative_to` half of the check.
    Here the recorded path deliberately climbs out of its own root with `..`
    and lands on a file that genuinely EXISTS in a sibling repo. Only the
    containment half can call this a phantom.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "sibling-repo").mkdir(parents=True)
    (projects / "sibling-repo" / "control.py").touch()
    (projects / "sample-repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "sample-repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("escapee", {"file": "../sibling-repo/control.py", "kind": "test"}),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    err = capsys.readouterr().err
    assert "phantom: ../sibling-repo/control.py (sample:escapee" in err


def test_corrupt_l1_corpus_exits_nonzero_not_a_clean_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S2/M31: the corpus-integrity except-arm is a GATE, not a log line.

    Every raise inside verify_enforcement (bad JSON, non-object record, bad
    `auto`, bad `enforcement`) reaches main() through one except arm. Nothing
    asserted that arm's exit code, so a corrupt corpus could be reported as a
    clean run.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    (l1_dir / "sample.jsonl").write_text(
        json.dumps(machine_record("ok", {"file": "control.py", "kind": "test"}))
        + "\n{ this is not json }\n",
        encoding="utf-8",
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 1
    err = capsys.readouterr().err
    assert "invalid JSON" in err


def test_total_enforcement_bearing_excludes_entries_that_enforce_nothing() -> None:
    """S3/M32: the debt floor counts units of WORK, not units PRESENT (FM-155).

    fleet#152: nulling out an `enforcement` value must lower this total. If
    the floor counted `machine` alone, a maintainer could strip every
    enforcement value in the corpus and DEBT-FLOOR would not notice.
    """
    report = MODULE.EnforcementReport(
        sources={
            "hollow": MODULE.SourceTotals(machine=3, unbacked=3, enforcement_bearing=0),
            "real": MODULE.SourceTotals(machine=2, unbacked=1, enforcement_bearing=1, checked=1),
        },
        phantoms=[],
        unverifiable=[],
        roots_resolved={},
        roots_unresolved={},
        mapped_sources=2,
    )

    # hollow contributes 0 (3 machine entries, all with enforcement: null);
    # real contributes exactly the 1 entry that carries a real claim.
    assert MODULE.total_enforcement_bearing(report) == 1


def test_nulling_every_enforcement_value_breaches_the_debt_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S3/M32, end-to-end: the floor must actually fire on hollowed-out entries."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    # Two machine entries; the enforcement value of one was removed. Present
    # count is still 2, but only 1 unit of enforcement work remains.
    write_records(
        l1_dir,
        "sample",
        machine_record("kept", {"file": "control.py", "kind": "test"}),
        machine_record("hollowed", None),
    )

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor=2
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "DEBT-FLOOR: 1 total enforcement-bearing entries (was 1 machine-only; floor 2)" in err


def test_malformed_enforcement_file_raises_and_is_not_relabelled_unbacked(
    tmp_path: Path,
) -> None:
    """S8/M34: a malformed claim is corpus corruption, not an honest gap.

    `{"enforcement": {"file": null}}` claims a mechanism and fails to name it.
    Silently counting it as `unbacked` would both skip the phantom check for
    it AND remove it from the enforcement-bearing total -- laundering a broken
    claim into "we never claimed anything".
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_records(l1_dir, "sample", {"id": "bad", "auto": "machine", "enforcement": {"file": None}})

    with pytest.raises(ValueError, match="invalid enforcement.file"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_empty_enforcement_file_string_also_raises(tmp_path: Path) -> None:
    """S8/M34, the other arm of the same condition: `"file": ""`."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_records(l1_dir, "sample", {"id": "bad", "auto": "machine", "enforcement": {"file": ""}})

    with pytest.raises(ValueError, match="invalid enforcement.file"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_require_roots_counts_roots_that_verified_something_not_roots_that_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S9/M33: the falsifiable root floor (FM-155).

    `test_require_roots_flag_raises_the_floor` has resolved == useful == 1, so
    it cannot tell the two counters apart. Here BOTH roots resolve (both
    directories are checked out) but only one of them had a single entry to
    actually check -- the other verified nothing. `--require-roots 2` must
    ERROR, because a floor satisfiable by an element that verifies nothing is
    not a floor.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo-a").mkdir(parents=True)
    write_executable(projects / "repo-a" / "control.py")
    (projects / "repo-b").mkdir(parents=True)  # resolves, but checks nothing
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"a": "repo-a", "b": "repo-b"})
    write_records(l1_dir, "a", machine_record("a-1", {"file": "control.py", "kind": "test"}))
    write_records(l1_dir, "b", machine_record("b-1", None))

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, extra_args=["--require-roots", "2"]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "only 1 of 2 mapped source roots actually verified an entry" in err
    assert "phantom:" not in err


def test_load_source_roots_raises_on_a_comment_only_map(tmp_path: Path) -> None:
    """S11/M30: the loader's OWN fail-loud contract.

    `test_empty_source_roots_conf_fails_loud` asserts only on main()'s exit
    code, which the downstream zero-roots check also produces -- so it passes
    even when the loader itself has been made to return an empty map. Pin the
    loader directly.
    """
    roots_path = tmp_path / "source-roots.conf"
    roots_path.write_text("# every line is a comment\n#\n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source-roots map is empty"):
        MODULE.load_source_roots(roots_path)


def test_unrecognised_auto_value_raises_instead_of_dropping_the_record(
    tmp_path: Path,
) -> None:
    """S12/M21: a typo must not delete a record from every total.

    `"Machine"` silently skipped means the entry vanishes from machine,
    judgment, the phantom check and the debt floor alike -- a way to shrink
    the corpus without shrinking any visible counter.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    write_records(
        l1_dir,
        "sample",
        {"id": "typo", "auto": "Machine", "enforcement": {"file": "control.py"}},
    )

    with pytest.raises(ValueError, match="invalid auto value"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_blank_l1_record_raises_instead_of_being_skipped(tmp_path: Path) -> None:
    """S13/M20: a blank line in the corpus is corruption, not whitespace."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    (l1_dir / "sample.jsonl").write_text(
        json.dumps(machine_record("one", {"file": "control.py", "kind": "test"}))
        + "\n\n"
        + json.dumps(machine_record("two", {"file": "control.py", "kind": "test"}))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"blank L1 record in .*sample\.jsonl:2"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


# ---------------------------------------------------------------------------
# Round-2 survivors (briefs/survivors/guard-survivors.md S1–S10, S3–S7, S9).
# Each test was proven to PASS on unmutated code and FAIL under its named
# mutant; a test that is green in both states kills nothing.
# ---------------------------------------------------------------------------


def test_M01_ledger_entry_for_a_different_claimed_path_does_not_excuse_this_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S1/M01: PhantomEntry.key() is a 3-tuple including enforcement_file.

    A ledger row for (source, id, OLD path) must not silence a phantom that
    now claims a different path. Ignoring the third element lets anyone
    rewrite enforcement.file to a fabricated path and keep exit 0.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir, "sample", machine_record("example", {"file": "bin/NEW-phantom.sh", "kind": "test"})
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "sample",
                "id": "example",
                "claimed_path": "bin/OLD-phantom.sh",
                "evidence": "ls showed OLD path missing once",
                "disposition": "genuine-phantom: historical claim",
            }
        ],
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "undocumented" in err
    assert "bin/NEW-phantom.sh" in err


@pytest.mark.parametrize(
    "bad_line",
    [
        "this-line-has-no-colon",
        ":repo2",
        "other:",
    ],
)
def test_M04_M05_malformed_source_roots_line_is_fatal_not_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bad_line: str,
) -> None:
    """S2/M04+M05: a typo in source-roots.conf must fail loud, not drop the map.

    Skipping a malformed line demotes that source to UNVERIFIABLE and can exit
    0 while real debt disappears from the fatal path.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    # One valid mapping so an empty-map check cannot absorb the failure;
    # the malformed line is the only thing that must make the loader raise.
    roots_path.write_text(f"sample:repo\n{bad_line}\n", encoding="utf-8")
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "malformed source-roots line" in err


def test_M30_a_file_where_a_checkout_should_be_is_not_a_resolved_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S3/M30: exists-but-not-a-directory is not a resolved source root.

    A stale file (or broken checkout) must hit the resolved_count == 0 hard
    ERROR, not be counted as present and slipped into the SKIPPED (return 0)
    branch reserved for roots that exist but check nothing.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    # A regular file where the mapped checkout directory should be.
    (projects / "repo").write_text("i am a file not a directory\n", encoding="utf-8")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    exit_code = run_verifier(monkeypatch, l1_dir, projects, roots_path)
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "0 of 1 mapped source roots" in err
    assert "SKIPPED" not in err


def test_judgment_entry_with_resolving_enforcement_is_checked_and_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A judgment is a totals label, not an exemption from path resolution."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir, "sample", judgment_record("judgment-ok", {"file": "control.py", "kind": "test"})
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path, enforcement_floor=1) == 0
    err = capsys.readouterr().err
    assert "phantom:" not in err
    assert "  sample: 0 1 0 0 0 1" in err


def test_judgment_entry_with_missing_enforcement_is_a_phantom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A judgment-tagged path claim must reach the same phantom gate as a machine claim."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir, "sample", judgment_record("judgment-missing", {"file": "missing.py", "kind": "test"})
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path, enforcement_floor=1) == 1
    assert "phantom: missing.py (sample:judgment-missing," in capsys.readouterr().err


def test_machine_entry_remains_checked_when_a_judgment_entry_is_also_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Widening eligibility must not change the established machine path behavior."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("machine-ok", {"file": "control.py", "kind": "test"}),
        judgment_record("judgment-ok", {"file": "control.py", "kind": "test"}),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path, enforcement_floor=2) == 0
    err = capsys.readouterr().err
    assert "phantom:" not in err
    assert "  sample: 1 1 0 0 0 2" in err


def test_debt_floor_counts_every_enforcement_bearing_row_and_reports_old_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The floor includes both auto categories while exposing the old subset."""
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("kept", {"file": "control.py", "kind": "test"}),
        machine_record("machine-unbacked", None),
        judgment_record("judgment-claim", {"file": "control.py", "kind": "test"}),
        judgment_record("judgment-unbacked", None),
    )

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor=2
    )
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "DEBT-FLOOR: 2 total enforcement-bearing entries (was 1 machine-only; floor 2)" in err


@pytest.mark.parametrize(
    "record",
    [
        # Missing evidence and disposition entirely.
        {
            "source": "sample",
            "id": "example",
            "claimed_path": "missing.py",
        },
        # Present but empty — still a silent allowlist entry.
        {
            "source": "sample",
            "id": "example",
            "claimed_path": "missing.py",
            "evidence": "",
            "disposition": "",
        },
    ],
)
def test_M02_M03_phantom_ledger_demands_nonempty_evidence_and_disposition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    record: dict[str, str],
) -> None:
    """S5/M02 + S6/M03: evidence and disposition are the ledger's load-bearing fields.

    Without them the file is a silent allowlist, not a debt ledger.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir, "sample", machine_record("example", {"file": "missing.py", "kind": "test"})
    )

    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, known_phantoms=[record]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "known-phantoms" in err.lower() or "missing required field" in err.lower()


def test_M13_empty_enforcement_object_is_malformed_not_relabelled_unbacked(
    tmp_path: Path,
) -> None:
    """S7/M13: enforcement: {} claims a mechanism and fails to name it.

    Relabelling it unbacked converts a hard corpus-integrity error into a
    benign WARNING path — a broken claim becomes "we never claimed anything".
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_records(l1_dir, "sample", {"id": "bad", "auto": "machine", "enforcement": {}})

    with pytest.raises(ValueError, match="invalid enforcement.file"):
        MODULE.verify_enforcement(l1_dir, projects, {"sample": "repo"})


def test_M23_multi_value_floor_file_is_fatal_not_first_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S9/M23: an ambiguous floor file must not silently adopt the first line.

    A half-resolved merge leaving two numbers can quietly weaken the gate if
    the lower value happens to come first.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    floor_path = tmp_path / "floor.conf"
    floor_path.write_text("0\n99\n", encoding="utf-8")
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, enforcement_floor_path=floor_path
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "exactly one value" in err


def test_M24_non_object_known_phantoms_line_is_fatal_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S10/M24: a non-object JSONL line in the debt ledger is corruption.

    Silently dropping it understates the printed DEBT count and removes
    ledger-file validation for that entry.
    """
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(l1_dir, "sample", machine_record("example", {"file": "control.py", "kind": "test"}))

    ledger_path = tmp_path / "known-phantoms.conf"
    ledger_path.write_text('["s","e1","bin/nope.sh"]\n', encoding="utf-8")
    exit_code = run_verifier(
        monkeypatch, l1_dir, projects, roots_path, known_phantoms_path=ledger_path
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "not an object" in err


# ---------------------------------------------------------------------------
# PLAN-01 / issue #18: advisory verification must disclose what it measured
# and what it could not measure, including on the CI-shaped SKIPPED path.
# ---------------------------------------------------------------------------


def test_P01_skip_discloses_debt_unbacked_and_not_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(
        roots_path,
        {
            "sample": "repo",
            "absent-a": "not-checked-out-a",
            "absent-b": "not-checked-out-b",
        },
    )
    write_records(l1_dir, "sample", machine_record("unbacked", None))
    write_records(
        l1_dir,
        "absent-a",
        machine_record("unchecked-a", {"file": "control.py", "kind": "test"}),
    )
    write_records(
        l1_dir,
        "absent-b",
        machine_record("unchecked-b", {"file": "control.py", "kind": "test"}),
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "elsewhere",
                "id": "known-debt",
                "claimed_path": "missing.py",
                "evidence": "documented fixture debt",
                "disposition": "genuine-phantom: fixture",
            }
        ],
    )
    err = capsys.readouterr().err

    assert exit_code == 0
    assert "enforcement-verifier: PHANTOM-DEBT: 1 documented in conf/known-phantoms.conf" in err
    assert "enforcement-verifier: UNBACKED: 1 machine entries carry enforcement: null" in err
    assert "enforcement-verifier: UNVERIFIABLE: 2 enforcement-bearing entries could not be checked" in err
    assert (
        "enforcement-verifier: PHANTOMS-MEASURED: NOT MEASURED HERE "
        "(ROOTS 1/3, 0 entries checked)"
    ) in err
    assert "SKIPPED" in err


def test_P01_checked_run_discloses_measured_zero_not_unmeasured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    write_executable(projects / "repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("checked", {"file": "control.py", "kind": "test"}),
        machine_record("unbacked", None),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    err = capsys.readouterr().err
    assert "enforcement-verifier: PHANTOM-DEBT: 0 documented in conf/known-phantoms.conf" in err
    assert "enforcement-verifier: UNBACKED: 1 machine entries carry enforcement: null" in err
    assert "enforcement-verifier: PHANTOMS-MEASURED: 0 across 1 source roots" in err
    assert "PHANTOMS-MEASURED: NOT MEASURED HERE" not in err


def test_P01_checked_run_discloses_actual_measured_phantom_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    write_records(
        l1_dir,
        "sample",
        machine_record("known-debt", {"file": "missing.py", "kind": "test"}),
    )

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms=[
            {
                "source": "sample",
                "id": "known-debt",
                "claimed_path": "missing.py",
                "evidence": "documented fixture debt",
                "disposition": "genuine-phantom: fixture",
            }
        ],
    )
    err = capsys.readouterr().err

    assert exit_code == 0
    assert "enforcement-verifier: PHANTOM-DEBT: 1 documented in conf/known-phantoms.conf" in err
    assert "enforcement-verifier: PHANTOMS-MEASURED: 1 across 1 source roots" in err


def test_P01_summary_distinguishes_unmeasured_from_measured_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "checked-repo").mkdir(parents=True)
    write_executable(projects / "checked-repo" / "control.py")
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(
        roots_path,
        {"checked": "checked-repo", "unmeasured": "not-checked-out"},
    )
    write_records(
        l1_dir,
        "checked",
        machine_record("checked", {"file": "control.py", "kind": "test"}),
    )
    write_records(
        l1_dir,
        "unmeasured",
        machine_record("not-checked", {"file": "control.py", "kind": "test"}),
    )

    assert run_verifier(monkeypatch, l1_dir, projects, roots_path) == 0
    err = capsys.readouterr().err
    assert (
        "summary (source machine judgment unbacked "
        "phantoms[-=not-measured] unverifiable checked)"
    ) in err
    assert "  checked: 1 0 0 0 0 1" in err
    assert "  unmeasured: 1 0 0 - 1 0" in err


@pytest.mark.parametrize("checked", [False, True], ids=["skipped", "checked"])
@pytest.mark.parametrize("ledger_state", ["missing", "malformed", "unreadable"])
def test_P01_all_environment_shapes_load_known_phantoms_ledger(
    ledger_state: str,
    checked: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    l1_dir = tmp_path / "L1"
    l1_dir.mkdir()
    projects = tmp_path / "projects"
    (projects / "repo").mkdir(parents=True)
    roots_path = tmp_path / "source-roots.conf"
    write_source_roots(roots_path, {"sample": "repo"})
    if checked:
        write_executable(projects / "repo" / "control.py")
        write_records(
            l1_dir,
            "sample",
            machine_record("checked", {"file": "control.py", "kind": "test"}),
        )
    else:
        write_records(l1_dir, "sample", machine_record("unbacked", None))
    ledger_path = tmp_path / "known-phantoms.conf"

    if ledger_state == "malformed":
        ledger_path.write_text("{not-json}\n", encoding="utf-8")
    elif ledger_state == "unreadable":
        ledger_path.write_text("", encoding="utf-8")
        original_read_text = Path.read_text

        def deny_ledger_read(path: Path, *args: object, **kwargs: object) -> str:
            if path == ledger_path:
                raise PermissionError(13, "Permission denied", str(path))
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", deny_ledger_read)

    exit_code = run_verifier(
        monkeypatch,
        l1_dir,
        projects,
        roots_path,
        known_phantoms_path=ledger_path,
    )
    err = capsys.readouterr().err

    assert exit_code == 1
    assert str(ledger_path) in err
    assert "known-phantoms.conf" in err


def test_committed_floor_has_no_slack_against_the_committed_corpus() -> None:
    """The floor in conf/ must equal what the gate actually counts today.

    Every other test in this file monkeypatches a synthetic floor, so none of
    them can see the real one drift. That is precisely how issue #31 nearly
    shipped a loosened ratchet: widening the counted population from 33 to 35
    while leaving conf/enforcement-floor.conf at 33 left two rows of slack, so
    nulling a real enforcement value would have passed green.

    Slack is the whole failure: if floor < measured, an entry can be deleted or
    its enforcement nulled and the fleet#152 gate stays silent. This asserts
    equality rather than `>=` deliberately -- adding an enforcement-bearing row
    must be accompanied by raising the floor, which is what the ratchet means.
    """
    source_roots = MODULE.load_source_roots(ROOT / "conf" / "source-roots.conf")
    # A deliberately absent projects dir: enforcement_bearing is root-independent,
    # so the count is identical here and on a CI runner with no repos checked out.
    report = MODULE.verify_enforcement(
        ROOT / "pipeline" / "L1", ROOT / "no-such-projects-dir", source_roots
    )
    measured = MODULE.total_enforcement_bearing(report)
    committed = int(
        [
            line.strip()
            for line in (ROOT / "conf" / "enforcement-floor.conf").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ][0]
    )
    assert measured == committed, (
        f"conf/enforcement-floor.conf says {committed} but the committed corpus carries "
        f"{measured} enforcement-bearing rows. "
        f"{'Slack of ' + str(measured - committed) + ' row(s): an entry could be deleted or nulled and the gate would stay green.' if measured > committed else 'The floor is above the corpus; the gate will fail every run.'}"
    )
