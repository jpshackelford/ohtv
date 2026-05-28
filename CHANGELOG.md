# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/).

Releases from this point forward are managed automatically by
[release-please](https://github.com/googleapis/release-please), driven by
[Conventional Commits](https://www.conventionalcommits.org/) on squash-merged PR subjects.
Direct pushes to `main` with `chore:` / `chore(worklog):` / `docs(worklog):` subjects (such
as `WORKLOG.md` updates) are intentionally ignored and never trigger a release.

## [0.13.0] - 2026-05-27

### Bootstrap release

First release under the automated `release-please` workflow. This entry consolidates
every pull request merged since the initial `0.1.0` version stamp — 62 PRs covering
the period **2026-04-13 → 2026-05-27** — and was hand-curated from the PR record because
conventional-commit subjects were not used consistently across the full history.
All subsequent entries will be generated automatically from the squash-merge subject line.

### Features — Sync & Cloud

- Add `-n/--max-new` option to limit how many conversations `sync` downloads per run (#11)
- Parallel downloads with progress bar and graceful shutdown in `sync` (#33)
- Support `OPENHANDS_API_KEY` environment variable for cloud auth (#41)
- Add `sync --repair` to check and fix sync state consistency (#42)
- Report conversation counts by directory in `sync --repair` (#72)
- Add `sync --update-metadata` to refresh cached title and labels (#93)
- Manifest now serves as a full cloud metadata cache (selected_repository, selected_branch, created_at); avoids re-opening `base_state.json` for fully-cached entries (#104)

### Features — Semantic Search & RAG

- Add semantic search with embeddings (`ohtv search`) (#25)
- Temporal filtering on `ohtv ask` (date / period filters reach the RAG retriever) (#31)
- Enrich RAG citations with conversation URLs, dates, and refs (#34)
- Add `ask --explain` flag for RAG retrieval debugging (#36)
- Embedding configuration wizard (`ohtv config-embed`) with Ollama and parallel processing support (#38)
- Track `cache_key` for analysis embeddings (#39)
- Move LLM analysis cache from per-conversation directories to `~/.ohtv` (#43)
- Database cleanup: detect and remove orphaned embeddings and duplicate conversations (#47)
- Include conversation ID and URL in RAG context passed to the LLM (#50)
- Progress bar for embedding generation during `sync` (#54)
- Support `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` environment overrides (#118)

### Features — Reporting & Analysis

- Multi-trajectory aggregate analysis jobs with period iteration (#27)
- Add `--agent` flag for multi-turn investigation mode (#62)
- Use agent-provided summary in action extraction instead of re-deriving (#74)
- Add `ohtv gen titles` to auto-rename placeholder-titled cloud conversations (#96)
- Add `ohtv fetch-loc` command to backfill LOC from the GitHub API (#97)
- Add `ohtv report velocity` command (#98)
- Add `ohtv classify` command (#99)
- Add `ohtv report weekly-counts` command (#100)
- Add `--chart` flag to `ohtv report velocity` for publication-quality PNG/SVG/PDF output (#101)
- Hatch `partial_loc` bars in velocity chart and document NULL LOC convention (#106)

### Features — Prompts & Extensibility

- Content restructure: YAML frontmatter and family directories for prompts (Phase 2) (#12)
- Prompt discovery and loading (Phase 3) (#14)
- Metadata-driven transcript building (Phase 4) (#15)
- Unified `ohtv analyze` CLI command (Phase 5) (#17)
- Extensible prompt system with unified `gen` command (#18)
- Consolidate `summary` command into `gen objs` (#21)
- Add display schema to prompt frontmatter for variant-aware table rendering (#24)

### Features — Database & Processing

- Initial SQLite indexing, `config` command, and CLI improvements (#2)
- Support configurable multiple conversation search paths (#10)
- Add `extra_conversation_paths` support to `db scan` (#16)
- Add database schema for contribution tracking (#84)
- Add `human_input` counting stage (#85)
- Add PR contribution detection stage (#88)
- Detect direct pushes to `main`/`master` in contributions (#94)

### Features — CLI Quality of Life

- Add `--quiet` option to `summary` (#8)
- `list`: add `--idle` flag and show refs by default (#40)
- Show start time, duration, and step count in `gen objs` display (#56)
- Numeric lookback for `-D` and `-W` options (e.g. `-D 7`) (#67)
- Show conversation labels in `gen objs` display (#73)
- Standardize progress bars via shared `make_progress` helper (#95)

### Bug Fixes

- Suppress LiteLLM debug spam and improve error visibility in `db embed` (#28)
- `prompts`: add `refs_display` to display schemas (#30)
- Embedding generation handles detailed analyses and orphaned cache correctly (#48)
- Embedding progress bar now displays remaining count and ETA (#55)
- Update prompt display schemas to 4-column layout (follow-up to #56) (#63)
- CLI context level `-c 3` now correctly converts to `full` so actions are captured (#65)
- Auto-promote context level for worker conversations (#66)
- `investigator`: update `tool_call` attribute access for openhands-sdk v1.21 (#68)
- Add `context_level` to skip cache key so higher levels can retry (#69)
- `investigator`: fix tool responses and improve investigation UX (#70)
- Fix `gen objs` sort order under parallel processing (#71)
- `charts`: wrap `ValueError` as `click.UsageError` for unsupported `--chart` extensions (#105)
- `sync`: sort by `updated_at DESC` in `reset_to_n_newest` (#117)

### Documentation

- Restructure README; split docs into `guides/`, `reference/`, and `design/` (#115)

## [0.1.0]

Initial project skeleton. See git history prior to `v0.13.0` for granular changes;
they are summarized in the 0.13.0 entry above.
