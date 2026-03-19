# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

"""Run a deterministic subset of TOML fixtures under MicroPython using unittest.

Usage examples:
    micropython tests/micropython/run_subset.py
    micropython tests/micropython/run_subset.py 30
    micropython tests/micropython/run_subset.py 30 50
    micropython tests/micropython/run_subset.py --scan-all

Positional args:
    1) subset size for valid and invalid fixtures (default: 25)
    2) subset size for invalid fixtures only (overrides arg 1 for invalid)

Flags:
    --scan-all  Scan all fixtures first to report full totals (uses more RAM)
"""

from pathlib import Path
import gc
import os
import sys
import unittest

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Any


class _Shared:
    repo_root: Path | None = None
    loads: Any = None
    decode_skipped_invalid = 0


DIR_FLAG = 0x4000


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


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except TypeError:
        # Some MicroPython ports do not accept explicit encoding arguments.
        with open(path, "r") as handle:
            return handle.read()
    except UnicodeError:
        return None


def _is_dir(path: str) -> bool:
    try:
        mode = os.stat(path)[0]
    except OSError:
        return False
    return (mode & DIR_FLAG) == DIR_FLAG


def _iter_dir(path: str):
    ilistdir = getattr(os, "ilistdir", None)
    if ilistdir is not None:
        return ilistdir(path)
    return [(name, None, None) for name in os.listdir(path)]


def _collect_toml_files(root: Path, limit: int | None = None) -> list[str]:
    stack = [str(root)]
    out: list[str] = []
    scanned_entries = 0

    while stack:
        current = stack.pop()
        for entry in _iter_dir(current):
            name = entry[0]
            if name in (".", ".."):
                continue

            if current.endswith("/"):
                path = current + name
            else:
                path = current + "/" + name

            is_dir = False
            if len(entry) >= 2 and entry[1] is not None:
                is_dir = (entry[1] & DIR_FLAG) == DIR_FLAG
            else:
                is_dir = _is_dir(path)

            if is_dir:
                stack.append(path)
            elif name.endswith(".toml"):
                out.append(path)
                if limit is not None and len(out) >= limit:
                    gc.collect()
                    return out

            scanned_entries += 1
            # Keep allocations in check on small MicroPython boards.
            if (scanned_entries & 63) == 0:
                gc.collect()

    return out


def _ratio(numer: int, denom: int) -> str:
    if denom == 0:
        return "0.0%"
    return "%.1f%%" % ((100.0 * numer) / denom)


def _parse_limits(argv: list[str]) -> tuple[int, int, bool]:
    max_valid = 1000
    max_invalid = 1000
    scan_all = False

    positional: list[str] = []
    for arg in argv[1:]:
        if arg == "--scan-all":
            scan_all = True
            continue
        positional.append(arg)

    if len(positional) >= 1:
        max_valid = int(positional[0])
        max_invalid = max_valid
    if len(positional) >= 2:
        max_invalid = int(positional[1])
    if len(positional) > 2:
        raise ValueError(
            "Usage: run_subset.py [max_valid] [max_invalid] [--scan-all]"
        )
    if max_valid < 0 or max_invalid < 0:
        raise ValueError("subset sizes must be >= 0")

    return max_valid, max_invalid, scan_all


def _relative(path: str) -> str:
    repo_root = _Shared.repo_root
    if repo_root is None:
        return path

    path_str = path
    root_str = str(repo_root)
    prefix = root_str + "/"
    if path_str.startswith(prefix):
        return path_str[len(prefix) :]
    return path_str


class ValidFixtureCase(unittest.TestCase):
    def __init__(self, fixture_path: str):
        super().__init__()
        self.fixture_path = fixture_path

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
    def __init__(self, fixture_path: str):
        super().__init__()
        self.fixture_path = fixture_path

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


def _build_suite(paths: list[str], case_type: Any) -> unittest.TestSuite:
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


def _run_suite_batched(
    runner: unittest.TextTestRunner,
    paths: list[str],
    case_type: Any,
    batch_size: int = 32,
) -> tuple[int, int, int]:
    total_run = 0
    total_pass = 0
    total_fail = 0

    suite = unittest.TestSuite()
    batch_count = 0

    for path in paths:
        suite.addTest(case_type(path))
        batch_count += 1
        if batch_count >= batch_size:
            run, passed, failed = _run_suite(runner, suite)
            total_run += run
            total_pass += passed
            total_fail += failed
            suite = unittest.TestSuite()
            batch_count = 0
            gc.collect()

    if batch_count:
        run, passed, failed = _run_suite(runner, suite)
        total_run += run
        total_pass += passed
        total_fail += failed
        gc.collect()

    return total_run, total_pass, total_fail


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

    max_valid, max_invalid, scan_all = _parse_limits(argv)

    valid_root = repo_root / "tests" / "data" / "valid"
    invalid_root = repo_root / "tests" / "data" / "invalid"
    if scan_all:
        valid_files = _collect_toml_files(valid_root)
        invalid_files = _collect_toml_files(invalid_root)
        valid_subset = valid_files[:max_valid]
        invalid_subset = invalid_files[:max_invalid]
    else:
        # Low-memory mode: only collect as many fixtures as we need to run.
        valid_subset = _collect_toml_files(valid_root, max_valid)
        invalid_subset = _collect_toml_files(invalid_root, max_invalid)
        valid_files = valid_subset
        invalid_files = invalid_subset

    gc.collect()

    _Shared.repo_root = repo_root
    _Shared.loads = loads
    _Shared.decode_skipped_invalid = 0

    runner = unittest.TextTestRunner(verbosity=1)

    print("Running valid subset:", len(valid_subset))
    v_run, v_pass, v_fail = _run_suite_batched(
        runner, valid_subset, ValidFixtureCase
    )

    print("Running invalid subset:", len(invalid_subset))
    i_run, i_reject, i_fail = _run_suite_batched(
        runner, invalid_subset, InvalidFixtureCase
    )

    print("=== MicroPython Fixture Subset Report ===")
    print("repo root:", repo_root)
    if scan_all:
        print("valid total:", len(valid_files), "| ran:", v_run)
        print("invalid total:", len(invalid_files), "| ran:", i_run)
    else:
        print("valid discovered (limited):", len(valid_subset), "| ran:", v_run)
        print("invalid discovered (limited):", len(invalid_subset), "| ran:", i_run)
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
    if scan_all:
        print("subset coverage valid:", _ratio(v_run, len(valid_files)))
        print("subset coverage invalid:", _ratio(i_run, len(invalid_files)))
    else:
        print("subset coverage valid: n/a (scan-all disabled)")
        print("subset coverage invalid: n/a (scan-all disabled)")
    print("decode-skipped invalid fixtures:", _Shared.decode_skipped_invalid)

    total_failures = v_fail + i_fail
    if total_failures:
        print("RESULT: FAIL (", total_failures, "fixture failures )")
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
