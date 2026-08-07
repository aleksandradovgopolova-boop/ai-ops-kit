# Regression Tests

Tests for specific bugs that were found and fixed. Each test should reference the bug/issue.

## What goes here

- Tests that reproduce a specific bug scenario
- Tests that verify a fix for a production incident
- Tests from the regression-corpus/ directory

## Naming convention

```python
# test_RC001_name_of_bug.py — references regression corpus case
# test_fix_issue_123.py — references GitHub issue
```

## Markers

```python
pytestmark = [pytest.mark.regression]
```
