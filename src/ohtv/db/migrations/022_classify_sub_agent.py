"""Widen ``conversation_human_input.initial_prompt_source`` CHECK constraint.

Issue #126. ``classify`` needs to mark sub-conversations (rows whose
``conversations.parent_conversation_id`` is non-NULL) with a value that
is distinct from the three operator-facing trigger types
(``'human'`` / ``'automation'`` / ``'unknown'``). The original PR
(#146 initial draft) proposed reusing ``'automation'``, but
``'automation'`` is a real trigger type meaning "an automation run
(cron / webhook) dispatched a conversation" — conflating it with
"a parent agent delegated to a sub-agent" breaks every downstream
report that wants to count automation-triggered work separately from
sub-agent delegations.

This migration adds ``'sub_agent'`` as the fourth allowed value. The
parent agent's trigger type is recoverable at any time by walking up
``parent_conversation_id`` to the root, so nothing is lost by giving
subs their own label.

SQLite does not support ``ALTER TABLE ... DROP CHECK``, so we follow
the canonical 12-step ALTER pattern (see migration 017 for the
precedent on ``change_refs.status``):

1. Disable FK enforcement (``PRAGMA foreign_keys = OFF``).
2. Create a *new* table with the wider CHECK.
3. Copy data, preserving primary keys.
4. Drop the original and rename the replacement into place.
5. Recreate the original index.
6. Re-enable FK enforcement.

Row IDs (the ``conversation_id`` text PK) are preserved verbatim so
any existing FK references from ``conversations`` resolve correctly
after the swap.

This migration is purely additive at the value level — every row in
the table keeps its existing value. The widening only authorizes
future ``classify`` runs to write ``'sub_agent'``; nothing about
existing rows changes.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Recreate ``conversation_human_input`` with a widened CHECK constraint."""

    fk_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        # 1. Create the replacement table under a temporary name.
        #    Same shape as migration 016, plus ``'sub_agent'`` in the CHECK.
        conn.execute("""
            CREATE TABLE conversation_human_input_new (
                conversation_id TEXT PRIMARY KEY,
                initial_prompt_words INTEGER NOT NULL DEFAULT 0,
                initial_prompt_source TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(initial_prompt_source IN
                          ('human', 'automation', 'unknown', 'sub_agent')),
                followup_word_count INTEGER NOT NULL DEFAULT 0,
                followup_message_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    ON DELETE CASCADE
            )
        """)

        # 2. Copy data verbatim. No value migration: existing rows keep
        #    whatever they had. The classify auto-step (see
        #    ``apply_sub_classification`` in src/ohtv/classify.py) will
        #    re-label any pre-existing sub rows on the next invocation.
        conn.execute("""
            INSERT INTO conversation_human_input_new
                (conversation_id, initial_prompt_words, initial_prompt_source,
                 followup_word_count, followup_message_count,
                 processed_at, event_count)
            SELECT
                conversation_id, initial_prompt_words, initial_prompt_source,
                followup_word_count, followup_message_count,
                processed_at, event_count
            FROM conversation_human_input
        """)

        # 3. Drop the original (which also drops attached indexes).
        conn.execute("DROP TABLE conversation_human_input")

        # 4. Rename the replacement into place. No other table references
        #    ``conversation_human_input_new``, so no FKs are perturbed.
        conn.execute(
            "ALTER TABLE conversation_human_input_new "
            "RENAME TO conversation_human_input"
        )

        # 5. Recreate the original index from migration 016.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_human_input_source "
            "ON conversation_human_input(initial_prompt_source)"
        )
    finally:
        if fk_enabled:
            conn.execute("PRAGMA foreign_keys = ON")
