# Integration Tests

End-to-end tests that exercise multiple modules together.

## What goes here

- Pipeline integration: preflight → execution → gates → delivery
- Cross-module workflows: context_compiler → tool_loop → evidence_collector
- Installer integration: init → status → update → validate

## What does NOT go here

- Single-module tests → `tests/unit/`
- Contract/interface tests → `tests/contracts/`
- Live environment tests → `tests/live/`
- Regression tests for specific bugs → `tests/regression/`

## Markers

```python
pytestmark = [pytest.mark.integration]
```
