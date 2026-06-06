"""Add the sustained-attention cap to conversation_engagement (Issue #184).

The v1 engagement algorithm gated only on the gap between ``Uᵢ`` and
the immediately preceding event (silence-tolerance threshold ``T``).
For overnight / set-and-forget conversations the agent fired events
every few minutes, so the silence gate stayed satisfied the whole
night and a 14-hour conversation was credited as 14 hours of
"engaged" time.

The v2 algorithm introduces a **second, semantically distinct**
constant: the sustained-attention window ``T_a``. It caps how far an
attended block may extend back from ``Uᵢ`` to ``Uᵢ₋₁``. See the module
docstring on :mod:`ohtv.db.stages.engagement` for the full conceptual
distinction and the proposed empirical-tuning plan (Issue #184 comment
thread).

This migration:

1. Adds two columns to ``conversation_engagement``:

   * ``sustained_attention_seconds`` — the ``T_a`` used for the row.
     ``NOT NULL DEFAULT 3600`` (1 h) so pre-v2 rows back-fill to the
     v2 default — they will be recomputed under the new algorithm
     anyway (see step 2).
   * ``algorithm_version`` — the version of ``compute_engagement``
     that produced the row. ``NOT NULL DEFAULT 1`` so pre-existing
     rows are correctly labelled "v1" until the stage re-runs.

2. Auto-invalidates the cached engagement results by deleting all
   rows from ``conversation_stages`` with ``stage = 'engagement'``.
   This forces the next ``ohtv db process engagement`` / ``ohtv db
   process all`` / ``ohtv sync`` to recompute every row under the v2
   algorithm. Users do **not** need to remember ``--force``.

   The existing ``conversation_engagement`` rows are *not* deleted —
   ``process_engagement`` upserts (``ON CONFLICT ... DO UPDATE``) so
   the rows are overwritten in place. Until the recompute runs,
   downstream queries continue to see the v1 numbers (clearly
   identifiable via ``algorithm_version = 1``).
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Extend ``conversation_engagement`` and invalidate cached stage rows."""

    conn.execute(
        "ALTER TABLE conversation_engagement "
        "ADD COLUMN sustained_attention_seconds INTEGER NOT NULL DEFAULT 3600"
    )
    conn.execute(
        "ALTER TABLE conversation_engagement "
        "ADD COLUMN algorithm_version INTEGER NOT NULL DEFAULT 1"
    )

    # Index for tuning-sweep queries that compare ``T_a`` variants
    # — mirrors the pattern of ``idx_conv_engagement_threshold``
    # from migration 023.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_engagement_attention_window "
        "ON conversation_engagement(sustained_attention_seconds)"
    )

    # Force auto-recompute on next stage run. We clear the stage
    # tracker rather than the data rows so:
    #   * Downstream queries keep working between upgrade and next
    #     processing pass (stale numbers, clearly labelled
    #     ``algorithm_version = 1``).
    #   * The next ``db process engagement`` (or ``all``, or
    #     ``sync``-driven processing) sees every conversation as
    #     pending and rewrites the row in place.
    conn.execute(
        "DELETE FROM conversation_stages WHERE stage = 'engagement'"
    )
