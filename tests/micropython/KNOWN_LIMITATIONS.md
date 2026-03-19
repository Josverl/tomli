# MicroPython Port Known Limitations

This file tracks currently accepted limitations for the MicroPython port when
running fixture coverage via:

```
micropython tests/micropython/run_subset.py 5000 5000
```

Current status after numeric + datetime/localtime + encoding/comment fixes:

- Full fixture failures: 0 (down from 32)
- Valid pass: 228 / 228
- Invalid rejection pass: 516 / 516

## Remaining Failure Patterns

None in the currently covered corpus (`tests/data/valid` + `tests/data/invalid`).

## Notes

Numeric grammar and datetime/localtime edge cases were previous primary
failure clusters. They were resolved by:

- replacing the MicroPython fallback number regex with a stricter manual matcher
- fixing float-vs-int classification for tokens like `0xDEADBEEF`
- forcing manual datetime/localtime matching when verbose regex mode is missing
- adding explicit range checks for time and timezone offset parts
- replacing `str.ljust` usage with manual right-zero padding
- fixing date-only fallback handling when a space is followed by a comment
- rejecting non-Unicode-scalar characters in `skip_until` paths (comments/literals)

## MicroPython API Gaps Log

This section is a running log of API differences observed while porting.

- `types.MappingProxyType` not available.
	Workaround: fallback to `dict` for immutable mapping usage sites.

- `functools.lru_cache` not available.
	Workaround: no-op decorator fallback.

- `sys.getrecursionlimit` not available.
	Workaround: fixed recursion limit fallback (`1000`).

- `re` lacks `VERBOSE` and rejects some complex expressions.
	Workaround: feature-detect and use manual fallback matchers where needed.

- `re.Match` API differs:
	- no `end()`
	- no `groups()` in some cases
	- `group()` needs an explicit index on some builds
	Workaround: compatibility helpers for end-position and group extraction.

- `pathlib` differences in MicroPython port:
	- `Path.cwd` missing
	- `resolve()` may return `str`
	- `relative_to` missing
	- `rglob` may yield `str`
	Workaround: normalize to `Path` and add string-based fallbacks.

- `str.ljust` not available in the tested MicroPython build.
	Workaround implemented: manual right-zero padding helper.

- Exception chaining warnings (`... from ...`) not supported in some runtime paths.
	Workaround: tolerated warning; avoid relying on chained-traceback behavior.
