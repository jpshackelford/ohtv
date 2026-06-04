"""Tests for ``analyze_objectives(cache_only=True)`` (Issue #161 AC).

When ``cache_only=True`` and the cache has no entry for the requested
parameter combination, the function MUST:

1. Return an :class:`AnalysisResult` (never raise).
2. Set ``analysis.goal`` to ``None`` and all list fields to ``[]``.
3. Set ``cost=0.0`` and ``from_cache=False``.
4. NEVER call the LLM (would happen via ``llm.completion``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def conv_dir(tmp_path: Path) -> Path:
    """Build a tiny conversation directory with a single event file."""
    cd = tmp_path / "abc12345"
    (cd / "events").mkdir(parents=True)
    (cd / "events" / "event-1.json").write_text(
        '{"kind": "MessageEvent", "id": "1", '
        '"timestamp": "2025-01-01T00:00:00Z", '
        '"source": "user", '
        '"llm_message": {"role": "user", "content": '
        '[{"type": "text", "text": "hello"}]}}'
    )
    return cd


class TestCacheOnlyMode:
    def test_cache_miss_returns_stub_no_llm(self, conv_dir):
        from ohtv.analysis.objectives import analyze_objectives

        # If the implementation were to call into the LLM, the patch
        # below would catch it. We patch at the SDK level (the only
        # call site analyze_objectives uses).
        with patch("openhands.sdk.llm.LLM.completion") as mock_completion:
            result = analyze_objectives(
                conv_dir,
                model="gpt-4o-mini",
                context="minimal",
                detail="brief",
                cache_only=True,
            )

        assert result.from_cache is False
        assert result.cost == 0.0
        assert result.analysis.goal is None
        assert result.analysis.primary_outcomes == []
        assert result.analysis.secondary_outcomes == []
        assert result.analysis.primary_objectives == []
        assert result.analysis.summary is None
        # Crucially: no LLM call was made.
        mock_completion.assert_not_called()

    def test_cache_only_preserves_metadata_on_stub(self, conv_dir):
        from ohtv.analysis.objectives import analyze_objectives

        result = analyze_objectives(
            conv_dir,
            context="minimal",
            detail="brief",
            assess=False,
            cache_only=True,
        )
        # The stub carries the context/detail/assess parameters so
        # downstream display logic can render the right schema.
        assert result.analysis.detail_level == "brief"
        assert result.analysis.assess is False
        assert result.analysis.conversation_id == "abc12345"
