"""Tests for opportunistic key-variant cache warming on context promotion.

Issue #145: when ``analyze_objectives`` auto-promotes the context level
(because the requested level produced an empty transcript), it
opportunistically warms the cache for sibling prompts in the ``objs`` family
whose frontmatter sets ``key_variant_on_promotion: true``.

The three tests below mirror the acceptance criteria in the issue:

1. Promotion happens → primary + every declared variant ends up cached after
   a single ``analyze_objectives`` call.
2. A variant is pre-populated in cache → fan-out detects the hit and skips
   the LLM round-trip for that variant.
3. One variant raises mid-fan-out → primary result is still returned and
   the other variant is still cached (failure isolation).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ohtv.analysis.cache import make_cache_key
from ohtv.analysis.objectives import (
    ObjectiveAnalysis,
    _cache_manager,
    analyze_objectives,
)
from ohtv.prompts import get_prompt_hash
from ohtv.prompts.discovery import (
    discover_prompts,
    list_key_variants_on_promotion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ohtv_dir(monkeypatch, tmp_path):
    """Redirect all ohtv-generated state into ``tmp_path`` and clear the
    discover_prompts cache so every test starts from a clean prompt scan."""
    ohtv_root = tmp_path / "ohtv_home"
    ohtv_root.mkdir()
    monkeypatch.setenv("OHTV_DIR", str(ohtv_root))
    # The lru_cache on discover_prompts persists across tests; clear it so
    # frontmatter changes from one test cannot leak into another.
    discover_prompts.cache_clear()
    yield ohtv_root
    discover_prompts.cache_clear()


@pytest.fixture
def worker_conv_dir(tmp_path):
    """Worker-style conversation: no user messages, single finish ActionEvent.

    This is the canonical shape that triggers the auto-promotion ladder in
    ``analyze_objectives`` — minimal context yields an empty transcript, but
    ``outcome`` level emits the finish summary so the loop stops there.
    """
    conv_dir = tmp_path / "conversations" / "deadbeefcafef00d1234567890abcdef"
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True)

    finish_event = {
        "id": "evt-0001",
        "timestamp": "2024-01-01T00:00:00Z",
        "source": "agent",
        "kind": "ActionEvent",
        "tool_name": "finish",
        "tool_call_id": "call-0001",
        "action": {"message": "All done."},
    }
    (events_dir / "event-00001-finish.json").write_text(json.dumps(finish_event))
    return conv_dir


def _mock_llm_response(payload: dict, cost: float = 0.0042):
    """Build a single fake LLM completion response wrapping ``payload``."""
    response_text = MagicMock()
    response_text.text = json.dumps(payload)
    response = MagicMock()
    response.message.content = [response_text]
    response.metrics.accumulated_cost = cost
    return response


@pytest.fixture
def mock_llm():
    """Patch ``openhands.sdk.LLM`` with a recording mock.

    Returns the ``completion`` MagicMock — its ``call_count`` is what tests
    assert against to detect skipped LLM calls.

    The default ``side_effect`` returns the same JSON payload for every call;
    individual tests can override ``completion.side_effect`` if they need
    different responses per variant (e.g. to simulate a JSON-parse failure).
    """
    completion_mock = MagicMock()
    completion_mock.return_value = _mock_llm_response(
        {
            "goal": "Test worker objective",
            "primary_outcomes": ["did the thing"],
            "secondary_outcomes": [],
            "status": "achieved",
        }
    )

    llm_instance = MagicMock()
    llm_instance.model = "test-model"
    llm_instance.api_key = "test-key"
    llm_instance.base_url = None
    llm_instance.timeout = 60
    llm_instance.completion = completion_mock

    with patch("openhands.sdk.LLM") as llm_class:
        llm_class.load_from_env.return_value = llm_instance
        llm_class.return_value = llm_instance
        yield completion_mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_cache_entries(conv_dir: Path) -> dict:
    """Read the ``analyses`` block from the conversation's cache file.

    The fan-out under test writes to ``~/.ohtv/cache/analysis/<id>/...``; the
    cache manager exposes ``get_cache_file`` for that resolution so this
    helper stays in sync with whatever path scheme the manager uses.
    """
    cache_file = _cache_manager.get_cache_file(conv_dir)
    assert cache_file.exists(), f"expected cache file at {cache_file}"
    data = json.loads(cache_file.read_text())
    return data.get("analyses", {})


# ---------------------------------------------------------------------------
# AC #9 — Primary + declared variants all cached after one analyze
# ---------------------------------------------------------------------------


def test_promotion_caches_primary_plus_all_declared_variants(
    ohtv_dir, worker_conv_dir, mock_llm
):
    """A single ``analyze_objectives`` call that triggers context promotion
    must result in cache entries for the primary AND every prompt in the
    ``objs`` family that declares ``key_variant_on_promotion: true``.
    """
    # Sanity: standard_assess is the one variant flagged today.
    declared = {m.variant for m in list_key_variants_on_promotion("objs")}
    assert "standard_assess" in declared, (
        "fixture assumes standard_assess.md ships with the opt-in flag; if "
        "this fails the prompt frontmatter regressed"
    )

    result = analyze_objectives(
        worker_conv_dir,
        model="test-model",
        context="minimal",
        detail="brief",
        assess=False,
    )

    # Primary did NOT come from cache (it's the first analyze).
    assert result.from_cache is False
    # Auto-promotion happened (otherwise the fan-out short-circuits).
    effective_context = result.analysis.context_level
    assert effective_context != "minimal"

    analyses = _load_cache_entries(worker_conv_dir)

    # Primary at the EFFECTIVE (promoted) context.
    primary_key = make_cache_key(
        context=effective_context, detail="brief", assess=False
    )
    assert primary_key in analyses, (
        f"primary key {primary_key!r} missing from cache (have: "
        f"{sorted(analyses)})"
    )

    # Every declared variant (excluding the primary's own (detail, assess))
    # at the EFFECTIVE context. This is the AC: "Each opportunistic variant
    # is cached at its own (promoted_context, variant_detail, variant_assess)
    # cache key".
    for variant in declared:
        if variant == "brief":  # would be the primary
            continue
        v_detail = variant[: -len("_assess")] if variant.endswith("_assess") else variant
        v_assess = variant.endswith("_assess")
        variant_key = make_cache_key(
            context=effective_context, detail=v_detail, assess=v_assess
        )
        assert variant_key in analyses, (
            f"declared variant {variant!r} not cached at {variant_key!r}; "
            f"have: {sorted(analyses)}"
        )

    # AC #6: AnalysisResult.cost reflects ONLY the primary, NOT the
    # opportunistic variants. Mock cost is 0.0042 per call; with two calls
    # (primary + 1 variant) a leaking implementation would surface 0.0084.
    assert result.cost == pytest.approx(0.0042), (
        f"AnalysisResult.cost must stay primary-only (got {result.cost}); "
        f"variant cost belongs in the INFO log, not the returned object"
    )


# ---------------------------------------------------------------------------
# AC #10 — Pre-populated variant short-circuits the LLM
# ---------------------------------------------------------------------------


def test_prepopulated_variant_cache_skips_llm_call(
    ohtv_dir, worker_conv_dir, mock_llm
):
    """If a key variant is already cached with a matching content_hash,
    event_count, and prompt_hash, the fan-out must skip the LLM call.

    We pre-populate the standard_assess slot at the *effective* (post-promotion)
    context so the cache_manager.load_cached check matches; then verify the
    LLM was invoked exactly once (the primary only).
    """
    # Force-build the data the fan-out will see by running a discovery + a
    # _prepare_data so we know what content_hash will be stored.
    from ohtv.analysis.objectives import (
        _prepare_data,
        promote_context_level,
    )

    # Walk the promotion ladder the same way analyze_objectives does so we
    # land on the effective context the LLM will see.
    current = "minimal"
    data = _prepare_data(worker_conv_dir, current)
    while not data.items:
        nxt = promote_context_level(current)
        if nxt is None:
            break
        current = nxt
        data = _prepare_data(worker_conv_dir, current)
    effective_context = current
    assert effective_context != "minimal", (
        "fixture should trigger promotion; if not, this test cannot exercise "
        "the cache-hit branch"
    )

    # Pre-populate ``standard_assess`` at the effective context. The stored
    # entry must carry the right content_hash + event_count + prompt_hash to
    # survive ``load_cached``'s validation.
    prepop = ObjectiveAnalysis(
        conversation_id=worker_conv_dir.name,
        analyzed_at=datetime.now(timezone.utc),
        model_used="test-model",
        event_count=len(data.events),
        content_hash=data.content_hash,
        prompt_hash=get_prompt_hash("standard_assess"),
        context_level=effective_context,
        detail_level="standard",
        assess=True,
        goal="pre-populated",
        primary_outcomes=["seeded"],
        secondary_outcomes=[],
    )
    _cache_manager.save(worker_conv_dir, prepop)

    # Sanity: the pre-populated entry is exactly where load_cached will look.
    expected_key = make_cache_key(
        context=effective_context, detail="standard", assess=True
    )
    seeded_analyses = _load_cache_entries(worker_conv_dir)
    assert expected_key in seeded_analyses, (
        f"pre-populated entry should land at {expected_key!r}; have "
        f"{sorted(seeded_analyses)}"
    )

    # Now run analyze_objectives. With the variant pre-cached, the fan-out
    # must hit the cache and NOT invoke the LLM for standard_assess.
    result = analyze_objectives(
        worker_conv_dir,
        model="test-model",
        context="minimal",
        detail="brief",
        assess=False,
    )

    assert result.from_cache is False, "primary itself should still run"
    # Exactly one LLM call: the primary. Standard_assess hit the cache.
    assert mock_llm.call_count == 1, (
        f"expected exactly 1 LLM call (primary only); got "
        f"{mock_llm.call_count}. The pre-populated variant should have hit "
        f"the cache and skipped the round-trip."
    )

    # The pre-populated standard_assess entry must NOT have been overwritten —
    # its sentinel goal "pre-populated" should still be there.
    post_analyses = _load_cache_entries(worker_conv_dir)
    assert post_analyses[expected_key].get("goal") == "pre-populated", (
        "fan-out must NOT overwrite a cached variant; the load_cached hit "
        "should be a hard no-op for that variant"
    )


# ---------------------------------------------------------------------------
# AC #11 — Failure isolation: one variant raises, the rest survive
# ---------------------------------------------------------------------------


def test_variant_failure_does_not_break_primary(
    ohtv_dir, worker_conv_dir, mock_llm, monkeypatch
):
    """If a key variant's LLM call raises mid-fan-out, the primary
    ``AnalysisResult`` must still be returned and any other variant must
    still be cached.

    To exercise the failure-isolation path with the single ``standard_assess``
    variant we ship today, we monkeypatch ``_warm_key_variant_cache``'s
    discovery helper to advertise an EXTRA synthetic variant that will fail,
    plus the real ``standard_assess`` which must still succeed.
    """
    import ohtv.analysis.objectives as objectives_mod

    real_variants = list_key_variants_on_promotion("objs")
    # Build a synthetic "broken" variant — we point it at the same metadata
    # as standard but use ``variant="bogus_assess"`` so it round-trips through
    # _parse_variant_name as (detail="bogus", assess=True). The LLM call will
    # be made for it; we make THAT call raise.
    from ohtv.prompts.metadata import PromptMetadata
    broken_meta = PromptMetadata(
        id="objs.bogus_assess",
        family="objs",
        variant="bogus_assess",
        description="synthetic broken variant",
        key_variant_on_promotion=True,
    )

    # Patch the discovery helper *as imported inside* the helper module.
    def fake_lister(family: str):
        return real_variants + [broken_meta]

    monkeypatch.setattr(
        "ohtv.prompts.discovery.list_key_variants_on_promotion",
        fake_lister,
    )

    # Also patch get_prompt / get_prompt_hash to satisfy the synthetic
    # variant — _warm_key_variant_cache will ask for both.
    real_get_prompt_hash = objectives_mod.__dict__.get("get_prompt_hash")
    # The helper imports `get_prompt_hash` from `ohtv.prompts` lazily inside
    # _warm_key_variant_cache. Patch at the source.
    real_get_prompt = None
    try:
        from ohtv.prompts import get_prompt as _gp
        real_get_prompt = _gp
    except Exception:
        pass

    real_ph_fn = None
    try:
        from ohtv.prompts import get_prompt_hash as _gph
        real_ph_fn = _gph
    except Exception:
        pass

    def fake_get_prompt(name: str) -> str:
        if name == "bogus_assess":
            return "you are a synthetic broken prompt"
        return real_get_prompt(name)  # type: ignore[misc]

    def fake_get_prompt_hash(name: str) -> str:
        if name == "bogus_assess":
            return "a" * 16
        return real_ph_fn(name)  # type: ignore[misc]

    monkeypatch.setattr("ohtv.prompts.get_prompt", fake_get_prompt)
    monkeypatch.setattr("ohtv.prompts.get_prompt_hash", fake_get_prompt_hash)
    # Capture the silenced unused-var warning by referencing them.
    _ = real_get_prompt_hash

    # Configure the LLM mock to raise on the synthetic broken prompt and
    # succeed otherwise. We key on the system-message text — the synthetic
    # variant gets the unique "synthetic broken prompt" system text.
    def maybe_raise(messages):
        sys_text = messages[0].content[0].text
        if "synthetic broken prompt" in sys_text:
            raise RuntimeError("simulated LLM failure for synthetic variant")
        return _mock_llm_response(
            {
                "goal": "ok",
                "primary_outcomes": [],
                "secondary_outcomes": [],
                "status": "achieved",
            }
        )

    mock_llm.side_effect = maybe_raise

    # Drive the analysis. Primary MUST be returned successfully.
    result = analyze_objectives(
        worker_conv_dir,
        model="test-model",
        context="minimal",
        detail="brief",
        assess=False,
    )

    assert result.from_cache is False
    assert result.analysis.context_level != "minimal"

    # Failure isolation: primary still got returned despite the synthetic
    # variant raising. Also, the OTHER (real) variant — standard_assess —
    # must still be cached.
    effective_context = result.analysis.context_level
    analyses = _load_cache_entries(worker_conv_dir)

    primary_key = make_cache_key(
        context=effective_context, detail="brief", assess=False
    )
    assert primary_key in analyses, "primary must be cached"

    standard_assess_key = make_cache_key(
        context=effective_context, detail="standard", assess=True
    )
    assert standard_assess_key in analyses, (
        f"non-failing variant standard_assess should still be cached; "
        f"have: {sorted(analyses)}"
    )

    # The failed synthetic variant must NOT be cached (its run raised before
    # cache_manager.save was reached).
    bogus_key = make_cache_key(
        context=effective_context, detail="bogus", assess=True
    )
    assert bogus_key not in analyses, (
        "a variant whose LLM call raised must not leave a cache entry"
    )
