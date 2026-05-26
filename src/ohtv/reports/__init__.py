"""Periodic reports built on top of the ohtv database index.

Each report is a pure-Python module that fetches data from
``~/.ohtv/index.db`` (the existing index DB used by every other
command) and shapes it into reusable rows. The Click CLI wrappers
live in ``ohtv.cli`` and call into these modules for both
human-facing (Rich table) and machine-readable (CSV) output.

The row-shaping entry points (e.g. ``velocity.aggregate_velocity``)
are intentionally importable from non-CLI code so downstream
features such as charting (issue #82) can reuse them.
"""
