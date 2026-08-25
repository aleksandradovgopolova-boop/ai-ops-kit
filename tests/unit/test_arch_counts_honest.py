"""B2: Architecture docs must not contain hardcoded counts that go stale.

Hardcoded counts like '51 агент', '104 модуля', '72 валидатора' drift as the codebase
changes. These must either be under validate_claims markers or removed entirely.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

# Patterns that match hardcoded counts of agents/modules/packages/validators
# These are the counts that go stale as the codebase evolves.
_STALE_COUNT_PATTERNS = [
    # "51 агент" / "104 модуля" / "72 валидатора" etc.
    re.compile(r"\d+\s+(агент|модул[ьяй]|пакет[аов]?|валидатор[аов]?)\b"),
    # "51 agents" / "104 modules" etc. (English)
    re.compile(r"\d+\s+(agents?|modules?|packages?|validators?)\b", re.IGNORECASE),
]

# Files to check — architecture docs that are in write_scope
_FILES_TO_CHECK = [
    PKG_ROOT / "AGENTS.md",
    PKG_ROOT / "docs" / "architecture" / "overview.md",
]

# Known exceptions: historical/point-in-time references that are OK to have counts
# (e.g., "72 коммита без conventional-префикса из 594" — a historical fact)
_EXCEPTIONS = [
    re.compile(r"\d+\s+коммит"),  # historical commit counts
    re.compile(r"\d+\s+находок"),  # historical audit findings
    re.compile(r"\d+\s+пар"),  # pair counts in layering context
    re.compile(r"\d+\s+цикл"),  # cycle counts
    re.compile(r"blocking-гейтов\s+MVP\s*[≤<>=]"),  # policy limits, not counts
    re.compile(r"v\d+"),  # version numbers
    re.compile(r"3\.0-срез"),  # version reference
    re.compile(r"§\d+"),  # section references
    re.compile(r"\d+\s+мин"),  # time references
]


def _is_excepted(line: str) -> bool:
    return any(pat.search(line) for pat in _EXCEPTIONS)


def _find_stale_counts(text: str, filepath: str) -> list[str]:
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        if _is_excepted(line):
            continue
        for pat in _STALE_COUNT_PATTERNS:
            m = pat.search(line)
            if m:
                findings.append(f"{filepath}:{i}: hardcoded count '{m.group()}'")
    return findings


def test_agents_md_no_hardcoded_arch_counts():
    """AGENTS.md must not have hardcoded counts of agents/modules/validators."""
    f = PKG_ROOT / "AGENTS.md"
    text = f.read_text(encoding="utf-8")
    findings = _find_stale_counts(text, str(f.relative_to(PKG_ROOT)))
    assert not findings, (
        "Hardcoded counts found in AGENTS.md — these go stale as the codebase changes. "
        "Remove the specific numbers or put them under validate_claims markers:\n"
        + "\n".join(findings)
    )


def test_overview_md_no_hardcoded_arch_counts():
    """docs/architecture/overview.md must not have hardcoded counts."""
    f = PKG_ROOT / "docs" / "architecture" / "overview.md"
    if not f.exists():
        pytest.skip("docs/architecture/overview.md not found")
    text = f.read_text(encoding="utf-8")
    findings = _find_stale_counts(text, str(f.relative_to(PKG_ROOT)))
    assert not findings, (
        "Hardcoded counts found in overview.md:\n" + "\n".join(findings)
    )
