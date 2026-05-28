"""Behavioral test harness for ``ohtv.sync`` (Issue #110).

This package provides:

* :mod:`tests.unit.sync.fakes` — :class:`FakeCloudClient`, a programmable
  in-memory stand-in for ``ohtv.sources.cloud.CloudClient`` that records every
  call (subsuming the old inline ``_RecordingCloudClient`` from
  ``tests/unit/test_sync.py``).
* :mod:`tests.unit.sync.builders` — :func:`make_trajectory_zip` and a
  :class:`ConvFactory` for assembling realistic payloads.
* :mod:`tests.unit.sync.strategies` — Hypothesis strategies for property
  tests.
* :mod:`tests.unit.sync.conftest` — pytest fixtures (``fake_cloud``,
  ``sync_manager_factory``, ``seeded_local_state``).
* :mod:`tests.unit.sync.test_harness_smoke` — sanity checks on the fake
  itself.
* :mod:`tests.unit.sync.test_behavioral` — the scenario suite tracking
  Issues #111/#112/#113 via ``xfail(strict=True)`` and ``skip`` markers.

See ``AGENTS.md`` and the issue #110 discussion for the migration plan and
scenario list.
"""
