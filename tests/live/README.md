# Live Tests

Tests that require external resources (API keys, network, real providers).

## What goes here

- Real provider calls (Anthropic, OpenAI) with test budgets
- End-to-end delivery to real git remotes
- Integration with external tools (Claude CLI, OpenSpec)

## Requirements

- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in environment
- Network access
- Tests should be skippable: `@pytest.mark.skipif(not has_api_key, reason="no key")`

## Markers

```python
pytestmark = [pytest.mark.live]
```

## Running

```bash
# Only live tests
python3 -m pytest tests/live/ -v -m live

# Skip live tests (default in CI)
python3 -m pytest tests/ -v -m "not live"
```
