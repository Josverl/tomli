# MicroPython Port Known Limitations

This file tracks currently accepted limitations for the MicroPython port when
running fixture coverage via:

```
micropython tests/micropython/run_subset.py 5000 5000
```

Current status after numeric grammar improvements:

- Full fixture failures: 10 (down from 32)
- Valid pass: 220 / 228
- Invalid rejection pass: 514 / 516

## Remaining Failure Patterns

### 1. Datetime and localtime handling (primary remaining cluster)

Common error:

- `AttributeError: 'str' object has no attribute 'ljust'`

Also includes a localtime parse coverage gap with message:

- `Expected newline or end of document after a statement`

Affected fixtures:

- `tests/data/valid/_external/toml-test/valid/datetime/local-time.toml`
- `tests/data/valid/_external/toml-test/valid/datetime/local.toml`
- `tests/data/valid/_external/toml-test/valid/datetime/milliseconds.toml`
- `tests/data/valid/_external/toml-test/valid/spec-1.1.0/common-27.toml`
- `tests/data/valid/_external/toml-test/valid/spec-1.1.0/common-30.toml`
- `tests/data/valid/_external/toml-test/valid/spec-1.1.0/common-33.toml`
- `tests/data/valid/dates-and-times/localtime.toml`
- `tests/data/invalid/_external/toml-test/invalid/datetime/offset-overflow-minute.toml`

### 2. Comment/pathological syntax corner case

Affected fixture:

- `tests/data/valid/_external/toml-test/valid/comment/everywhere.toml`

### 3. Encoding/unicode codepoint corner case

Affected fixture:

- `tests/data/invalid/_external/toml-test/invalid/encoding/bad-codepoint.toml`

## Notes

Numeric grammar edge cases were the previous primary failure cluster.
Those were substantially reduced by replacing the MicroPython fallback number
regex with a stricter manual matcher and by fixing float-vs-int classification
for tokens like `0xDEADBEEF`.
