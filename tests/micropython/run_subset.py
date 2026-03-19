# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

"""Run a deterministic subset of TOML fixtures under MicroPython using unittest.

Usage examples:
    micropython tests/micropython/run_subset.py
    micropython tests/micropython/run_subset.py 30
    micropython tests/micropython/run_subset.py 30 50

Positional args:
    1) subset size for valid and invalid fixtures (default: 25)
    2) subset size for invalid fixtures only (overrides arg 1 for invalid)
"""

from pathlib import Path
import sys
import unittest

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Any


class _Shared:
    repo_root: Path | None = None
    loads: Any = None
    decode_skipped_invalid = 0


def _find_repo_root(start: Path | str) -> Path | None:
    cur = Path(start)
    resolved = cur.resolve()
    cur = Path(resolved)
    while True:
        if (cur / "src").is_dir() and (cur / "tests").is_dir():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def _read_text(path: Path) -> str | None:
    path = Path(path)
    try:
        return path.read_text("utf-8")
    except TypeError:
        # Some pathlib ports do not accept explicit encoding arguments.
        return path.read_text()
    except UnicodeError:
        return None


def _ratio(numer: int, denom: int) -> str:
    if denom == 0:
        return "0.0%"
    return "%.1f%%" % ((100.0 * numer) / denom)


def _parse_limits(argv: list[str]) -> tuple[int, int]:
    max_valid = 25
    max_invalid = 25

    if len(argv) >= 2:
        max_valid = int(argv[1])
        max_invalid = max_valid
    if len(argv) >= 3:
        max_invalid = int(argv[2])
    if len(argv) > 3:
        raise ValueError("Usage: run_subset.py [max_valid] [max_invalid]")
    if max_valid < 0 or max_invalid < 0:
        raise ValueError("subset sizes must be >= 0")

    return max_valid, max_invalid


def _relative(path: Path) -> str:
    path = Path(path)
    repo_root = _Shared.repo_root
    if repo_root is None:
        return str(path)

    relative_to = getattr(path, "relative_to", None)
    if relative_to is not None:
        try:
            return str(relative_to(repo_root))
        except ValueError:
            return str(path)

    path_str = str(path)
    root_str = str(repo_root)
    prefix = root_str + "/"
    if path_str.startswith(prefix):
        return path_str[len(prefix) :]
    return path_str


class ValidFixtureCase(unittest.TestCase):
    def __init__(self, fixture_path: Path):
        super().__init__()
        self.fixture_path = Path(fixture_path)

    def __str__(self) -> str:
        return "valid: %s" % _relative(self.fixture_path)

    def runTest(self) -> None:
        text = _read_text(self.fixture_path)
        if text is None:
            self.fail("UTF-8 decode failed")

        loads = _Shared.loads
        if loads is None:
            self.fail("tomli loader is not initialized")

        try:
            loads(text)
        except Exception as exc:
            self.fail("%s: %s" % (type(exc).__name__, exc))


class InvalidFixtureCase(unittest.TestCase):
    def __init__(self, fixture_path: Path):
        super().__init__()
        self.fixture_path = Path(fixture_path)

    def __str__(self) -> str:
        return "invalid: %s" % _relative(self.fixture_path)

    def runTest(self) -> None:
        text = _read_text(self.fixture_path)
        if text is None:
            # Some fixtures are intentionally non-UTF8. Treat as unsupported here.
            _Shared.decode_skipped_invalid += 1
            return

        loads = _Shared.loads
        if loads is None:
            self.fail("tomli loader is not initialized")

        try:
            loads(text)
        except Exception:
            return

        self.fail("Expected invalid TOML to raise parse error")


def _build_suite(paths: list[Path], case_type: Any) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for path in paths:
        suite.addTest(case_type(path))
    return suite


def _run_suite(
    runner: unittest.TextTestRunner, suite: unittest.TestSuite
) -> tuple[int, int, int]:
    result = runner.run(suite)
    failures = len(result.failures) + len(result.errors)
    passed = result.testsRun - failures
    return result.testsRun, passed, failures


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    repo_root = _find_repo_root(Path(".").resolve())
    if repo_root is None:
        print("ERROR: could not locate repo root (expected src/ and tests/)")
        return 2

    src_dir = repo_root / "src"
    src_str = str(src_dir)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)

    from tomli import loads

    max_valid, max_invalid = _parse_limits(argv)

    valid_files = [
        Path(p) for p in sorted((repo_root / "tests" / "data" / "valid").rglob("*.toml"))
    ]
    invalid_files = [
        Path(p)
        for p in sorted((repo_root / "tests" / "data" / "invalid").rglob("*.toml"))
    ]

    valid_subset = valid_files[:max_valid]
    invalid_subset = invalid_files[:max_invalid]

    _Shared.repo_root = repo_root
    _Shared.loads = loads
    _Shared.decode_skipped_invalid = 0

    runner = unittest.TextTestRunner(verbosity=1)

    print("Running valid subset:", len(valid_subset))
    v_run, v_pass, v_fail = _run_suite(
        runner, _build_suite(valid_subset, ValidFixtureCase)
    )

    print("Running invalid subset:", len(invalid_subset))
    i_run, i_reject, i_fail = _run_suite(
        runner, _build_suite(invalid_subset, InvalidFixtureCase)
    )

    print("=== MicroPython Fixture Subset Report ===")
    print("repo root:", repo_root)
    print("valid total:", len(valid_files), "| ran:", v_run)
    print("invalid total:", len(invalid_files), "| ran:", i_run)
    print("valid parse pass:", v_pass, "/", v_run, "(", _ratio(v_pass, v_run), ")")
    print(
        "invalid rejection pass:",
        i_reject,
        "/",
        i_run,
        "(",
        _ratio(i_reject, i_run),
        ")",
    )
    print("subset coverage valid:", _ratio(v_run, len(valid_files)))
    print("subset coverage invalid:", _ratio(i_run, len(invalid_files)))
    print("decode-skipped invalid fixtures:", _Shared.decode_skipped_invalid)

    total_failures = v_fail + i_fail
    if total_failures:
        print("RESULT: FAIL (", total_failures, "fixture failures )")
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
