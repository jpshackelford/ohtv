# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/).

Releases from this point forward are managed automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/), driven by
[Conventional Commits](https://www.conventionalcommits.org/) on squash-merged PR subjects.
Each release-bumping merge tags directly on `main` (no intermediate release PR).
Direct pushes to `main` with `chore:` / `chore(worklog):` / `docs(worklog):` subjects (such
as `WORKLOG.md` updates) are intentionally ignored and never trigger a release.

## [0.14.0](https://github.com/jpshackelford/ohtv/compare/ohtv-v0.13.0...ohtv-v0.14.0) (2026-05-29)


### Features

* add --agent flag for multi-turn investigation mode ([#62](https://github.com/jpshackelford/ohtv/issues/62)) ([be03c0c](https://github.com/jpshackelford/ohtv/commit/be03c0c31cf20d2bf5e42d752198d17229f424df))
* add --agent flag for multi-turn investigation mode ([#62](https://github.com/jpshackelford/ohtv/issues/62)) ([be03c0c](https://github.com/jpshackelford/ohtv/commit/be03c0c31cf20d2bf5e42d752198d17229f424df)), closes [#51](https://github.com/jpshackelford/ohtv/issues/51)
* add `ohtv report velocity` command ([#81](https://github.com/jpshackelford/ohtv/issues/81)) ([fd9f84e](https://github.com/jpshackelford/ohtv/commit/fd9f84e9bfbcbeb65184ac7baa9f075a7d16cdfc))
* Add conversation labels to gen objs display ([a2ee3cf](https://github.com/jpshackelford/ohtv/commit/a2ee3cf3a51f442c856995ab19376849c484d9bf))
* Add conversation labels to gen objs display ([#73](https://github.com/jpshackelford/ohtv/issues/73)) ([a2ee3cf](https://github.com/jpshackelford/ohtv/commit/a2ee3cf3a51f442c856995ab19376849c484d9bf))
* add database schema for contribution tracking ([#84](https://github.com/jpshackelford/ohtv/issues/84)) ([4395eb2](https://github.com/jpshackelford/ohtv/commit/4395eb26d093f9c182ef592ba1d223003c0562c1)), closes [#76](https://github.com/jpshackelford/ohtv/issues/76)
* add error analysis for agent/LLM errors (fixes [#4](https://github.com/jpshackelford/ohtv/issues/4)) ([8548b04](https://github.com/jpshackelford/ohtv/commit/8548b0464fac8a8c367dc0a439c917d6fa47a0a1))
* add error counts to show command stats ([0029a4b](https://github.com/jpshackelford/ohtv/commit/0029a4b39bb9d57ca3c12600b1b2a82d8ebab121))
* add fetch-loc command to backfill LOC from GitHub API ([#80](https://github.com/jpshackelford/ohtv/issues/80)) ([31917be](https://github.com/jpshackelford/ohtv/commit/31917bea8f73ef1dd59a4905332dcf7b31e295c7))
* add human_input counting stage ([#85](https://github.com/jpshackelford/ohtv/issues/85)) ([38d5032](https://github.com/jpshackelford/ohtv/commit/38d5032472ab9ef7e65836ff91480309ca29d89d))
* add numeric lookback for -D and -W options ([32cd31c](https://github.com/jpshackelford/ohtv/commit/32cd31c055934e771151c714ede6237ac616ecbc)), closes [#57](https://github.com/jpshackelford/ohtv/issues/57)
* add numeric lookback for -D and -W options ([#67](https://github.com/jpshackelford/ohtv/issues/67)) ([32cd31c](https://github.com/jpshackelford/ohtv/commit/32cd31c055934e771151c714ede6237ac616ecbc))
* add ohtv classify command ([#83](https://github.com/jpshackelford/ohtv/issues/83)) ([ae38940](https://github.com/jpshackelford/ohtv/commit/ae38940854b3e2edf5178cd37304bcbac24f64ec))
* add ohtv report weekly-counts command ([#92](https://github.com/jpshackelford/ohtv/issues/92)) ([c3b0f64](https://github.com/jpshackelford/ohtv/commit/c3b0f6456e73be147b703a88af79536b167b9570))
* add PR contribution detection stage ([#88](https://github.com/jpshackelford/ohtv/issues/88)) ([6212195](https://github.com/jpshackelford/ohtv/commit/6212195eda79c7d4e0d76d8f31399a6d7de47f5f)), closes [#78](https://github.com/jpshackelford/ohtv/issues/78)
* Add progress bar for embedding generation during sync ([3a3a37b](https://github.com/jpshackelford/ohtv/commit/3a3a37b75c636d198deb53ea668a244dc98f1443)), closes [#44](https://github.com/jpshackelford/ohtv/issues/44)
* Add progress bar for embedding generation during sync ([#54](https://github.com/jpshackelford/ohtv/issues/54)) ([3a3a37b](https://github.com/jpshackelford/ohtv/commit/3a3a37b75c636d198deb53ea668a244dc98f1443))
* add semantic search with embeddings ([#25](https://github.com/jpshackelford/ohtv/issues/25)) ([349c79e](https://github.com/jpshackelford/ohtv/commit/349c79e71154436d55729bff07e16d9215fe54cf))
* add semantic search with embeddings ([#25](https://github.com/jpshackelford/ohtv/issues/25)) ([349c79e](https://github.com/jpshackelford/ohtv/commit/349c79e71154436d55729bff07e16d9215fe54cf)), closes [#1](https://github.com/jpshackelford/ohtv/issues/1)
* Add temporal filtering to RAG ask command ([#29](https://github.com/jpshackelford/ohtv/issues/29)) ([#31](https://github.com/jpshackelford/ohtv/issues/31)) ([ad676b6](https://github.com/jpshackelford/ohtv/commit/ad676b65059ca6271237b2a446e4a742c58c7078))
* **ask:** add --explain and --explain-only flags for RAG retrieval debugging ([c1fded2](https://github.com/jpshackelford/ohtv/commit/c1fded27956741a4f2cb6ec7c2953161b20ab0a6)), closes [#35](https://github.com/jpshackelford/ohtv/issues/35)
* **charts:** hatch partial_loc bars + document NULL LOC convention ([#103](https://github.com/jpshackelford/ohtv/issues/103)) ([d7788da](https://github.com/jpshackelford/ohtv/commit/d7788da4a30ecdad581f43c5f55fba3aacc54b5e))
* **config:** support OPENHANDS_API_KEY environment variable ([d4e3799](https://github.com/jpshackelford/ohtv/commit/d4e37995dd9bf0abd85b183b28913734f6beafcb))
* **contributions:** detect direct pushes to main/master ([#79](https://github.com/jpshackelford/ohtv/issues/79)) ([03657ed](https://github.com/jpshackelford/ohtv/commit/03657edb152a45ee0e476af73de37c93f6fc2d4c))
* Database cleanup - orphaned embeddings and duplicate conversations ([#47](https://github.com/jpshackelford/ohtv/issues/47)) ([34e8ce0](https://github.com/jpshackelford/ohtv/commit/34e8ce0bd121fa6ddb6b3b63845fd5c7b1581be5))
* **db:** Add extra_conversation_paths support to scanner ([#16](https://github.com/jpshackelford/ohtv/issues/16)) ([3f810ed](https://github.com/jpshackelford/ohtv/commit/3f810edeb3fd74084bf1d490dfbe94cd9d7277a7))
* **db:** add set-diff sync schema (migration 018) ([#112](https://github.com/jpshackelford/ohtv/issues/112)) ([f2ccbab](https://github.com/jpshackelford/ohtv/commit/f2ccbab54b59c988c239e2405fc7d327cc6e8297))
* **embed:** add Ollama support and parallel processing ([17cc991](https://github.com/jpshackelford/ohtv/commit/17cc991fb108e586ead67b05ee697607763e0a97))
* **embed:** add Ollama support and parallel processing ([#28](https://github.com/jpshackelford/ohtv/issues/28)) ([17cc991](https://github.com/jpshackelford/ohtv/commit/17cc991fb108e586ead67b05ee697607763e0a97))
* **embeddings:** support EMBEDDING_API_KEY / EMBEDDING_BASE_URL overrides ([#118](https://github.com/jpshackelford/ohtv/issues/118)) ([1a968ce](https://github.com/jpshackelford/ohtv/commit/1a968ced09bc4a838cc67763689a81d657d2c8a9))
* enhance RAG citations with conversation URLs, dates, and refs ([#34](https://github.com/jpshackelford/ohtv/issues/34)) ([ceb56fb](https://github.com/jpshackelford/ohtv/commit/ceb56fb52debcae4816164e2561ebf010949c107))
* enhance RAG citations with URLs, dates, refs, and contextual retrieval ([ceb56fb](https://github.com/jpshackelford/ohtv/commit/ceb56fb52debcae4816164e2561ebf010949c107)), closes [#32](https://github.com/jpshackelford/ohtv/issues/32)
* extensible prompt system with unified gen command ([#18](https://github.com/jpshackelford/ohtv/issues/18)) ([2361041](https://github.com/jpshackelford/ohtv/commit/236104173b917e6bee4ee57a46f84bd56cbc86a7))
* **gen-objs:** add start time, duration, and step count to batch display ([dfc2d8f](https://github.com/jpshackelford/ohtv/commit/dfc2d8f1a715cb4c763db4a8ad63a055e2c6a9db)), closes [#52](https://github.com/jpshackelford/ohtv/issues/52)
* **gen-titles:** add `ohtv gen titles` to auto-rename placeholder-titled cloud conversations ([#89](https://github.com/jpshackelford/ohtv/issues/89)) ([bc1052e](https://github.com/jpshackelford/ohtv/commit/bc1052e73b4f1cd370b1e5967b22dfd4aac27967))
* implement show command for viewing conversation content ([99633e0](https://github.com/jpshackelford/ohtv/commit/99633e00f60628007ca3fe391e16a2e86feed0af))
* **list:** add --idle flag and show refs by default ([#40](https://github.com/jpshackelford/ohtv/issues/40)) ([a9c41d9](https://github.com/jpshackelford/ohtv/commit/a9c41d9fbfcb874281aab1a035c6925c26859769))
* **list:** add date filtering options (--since, --until, --day, --week) ([8612b12](https://github.com/jpshackelford/ohtv/commit/8612b124bbe01df7b49c92afe813f89edbb1d7b6))
* **locks:** add sync.lock writer mutex with --lock-timeout flag ([#109](https://github.com/jpshackelford/ohtv/issues/109)) ([4799ad0](https://github.com/jpshackelford/ohtv/commit/4799ad03e17b4f75130b11f0a9b3dcf8c050b7a6))
* move LLM analysis cache to centralized location ([#43](https://github.com/jpshackelford/ohtv/issues/43)) ([4e0c9bc](https://github.com/jpshackelford/ohtv/commit/4e0c9bc80fb08643a77547b87db3ac30e1e7ff5d)), closes [#7](https://github.com/jpshackelford/ohtv/issues/7)
* Multi-trajectory aggregate analysis jobs with period iteration ([#27](https://github.com/jpshackelford/ohtv/issues/27)) ([f62ffad](https://github.com/jpshackelford/ohtv/commit/f62ffadf5e4c3c48751b8b7bb75da0ddc78ff8d0)), closes [#22](https://github.com/jpshackelford/ohtv/issues/22)
* **prompts:** add display schema for variant-aware table rendering ([d08c871](https://github.com/jpshackelford/ohtv/commit/d08c871e0308a91c6fd1f874f29594728b84f33d)), closes [#23](https://github.com/jpshackelford/ohtv/issues/23)
* **prompts:** add display schema for variant-aware table rendering ([#24](https://github.com/jpshackelford/ohtv/issues/24)) ([d08c871](https://github.com/jpshackelford/ohtv/commit/d08c871e0308a91c6fd1f874f29594728b84f33d))
* **rag:** include conversation ID and URL in RAG context ([5960369](https://github.com/jpshackelford/ohtv/commit/59603695528a2fa98090f4562c2493788888aa5b)), closes [#49](https://github.com/jpshackelford/ohtv/issues/49)
* **refs:** add --actions flag to show only write actions ([88b20aa](https://github.com/jpshackelford/ohtv/commit/88b20aad6d3d119fb1a2dcb6d166e541d9904b6d))
* **refs:** add interaction type detection for refs command ([040c9cb](https://github.com/jpshackelford/ohtv/commit/040c9cb0710cdecc4e6b231385c5cbc90d65b569))
* Report conversation counts by directory in sync --repair ([#72](https://github.com/jpshackelford/ohtv/issues/72)) ([2337ec1](https://github.com/jpshackelford/ohtv/commit/2337ec1e94f90bf53b5a23bccd5936db84de9abe))
* **reports:** add --chart flag to velocity for publication-quality charts ([#82](https://github.com/jpshackelford/ohtv/issues/82)) ([77ce880](https://github.com/jpshackelford/ohtv/commit/77ce8804dab8be223b27bcbe3e9d75bfe7785a01))
* **show:** add --refs flag to display write actions summary ([5562c81](https://github.com/jpshackelford/ohtv/commit/5562c8165be2b9f794ee02c4e5295c4841d98186))
* **show:** add human-readable action details and flexible output options ([f0d46e2](https://github.com/jpshackelford/ohtv/commit/f0d46e2f244dfc7177e4eec46c1734e9213c1f5a))
* SQLite indexing, config command, and CLI improvements ([#2](https://github.com/jpshackelford/ohtv/issues/2)) ([66d3a5b](https://github.com/jpshackelford/ohtv/commit/66d3a5b65d809f63d172b85b20a64132cbcf2958))
* standardize progress bars via shared make_progress helper ([#91](https://github.com/jpshackelford/ohtv/issues/91)) ([c594d92](https://github.com/jpshackelford/ohtv/commit/c594d923ed86778bd04c89aa47de8ea33db62417))
* **sync:** add --repair option to check and fix sync state consistency ([d235f32](https://github.com/jpshackelford/ohtv/commit/d235f32353579f6980a88051d34b16d0ebf9684a))
* **sync:** add --repair option to check and fix sync state consistency ([#42](https://github.com/jpshackelford/ohtv/issues/42)) ([d235f32](https://github.com/jpshackelford/ohtv/commit/d235f32353579f6980a88051d34b16d0ebf9684a))
* **sync:** add --update-metadata to refresh cached title + labels ([#93](https://github.com/jpshackelford/ohtv/issues/93)) ([89a1352](https://github.com/jpshackelford/ohtv/commit/89a135268e8fa3fc88621f647482174b3f1c248f))
* **sync:** add parallel downloads with progress bar and graceful shutdown ([35ad387](https://github.com/jpshackelford/ohtv/commit/35ad387e9ae821dae745576e4fb3df1c7b1a2189))
* **sync:** add parallel downloads with progress bar and graceful shutdown ([#33](https://github.com/jpshackelford/ohtv/issues/33)) ([35ad387](https://github.com/jpshackelford/ohtv/commit/35ad387e9ae821dae745576e4fb3df1c7b1a2189))
* **sync:** add per-directory conversation counts in repair report ([2337ec1](https://github.com/jpshackelford/ohtv/commit/2337ec1e94f90bf53b5a23bccd5936db84de9abe)), closes [#46](https://github.com/jpshackelford/ohtv/issues/46)
* **sync:** include sub-conversations in cloud listing ([#108](https://github.com/jpshackelford/ohtv/issues/108)) ([211d9ba](https://github.com/jpshackelford/ohtv/commit/211d9ba4388b62d937b15059f234c39d15ca977d))
* **sync:** manifest as full cloud metadata cache ([#87](https://github.com/jpshackelford/ohtv/issues/87)) ([d3d3f9c](https://github.com/jpshackelford/ohtv/commit/d3d3f9ccd028b5c1d32830b319f40c4d044fac60))
* **sync:** recover from cloud/local gap via set-diff engine ([#111](https://github.com/jpshackelford/ohtv/issues/111)) ([92a2805](https://github.com/jpshackelford/ohtv/commit/92a2805b9ffe04282e5e08dd7a19aa42793a5d31))
* **sync:** rewrite --repair into four-category reconciliation ([#113](https://github.com/jpshackelford/ohtv/issues/113)) ([764410d](https://github.com/jpshackelford/ohtv/commit/764410d85ad94e23fd98ada26978f2a89ef873c9))
* **tests:** cloud-sync behavioral harness ([#110](https://github.com/jpshackelford/ohtv/issues/110)) ([d2465f3](https://github.com/jpshackelford/ohtv/commit/d2465f3e89b55ba62e4f7b6c6fff323072cd55d1))
* track cache_key for analysis embeddings ([947e526](https://github.com/jpshackelford/ohtv/commit/947e5261cc2a63a78031c69333a51240cef94f6d))
* track cache_key for analysis embeddings ([#39](https://github.com/jpshackelford/ohtv/issues/39)) ([947e526](https://github.com/jpshackelford/ohtv/commit/947e5261cc2a63a78031c69333a51240cef94f6d))
* Use agent-provided summary in action extraction ([73afe1a](https://github.com/jpshackelford/ohtv/commit/73afe1a483c2a62b78281fee4b53c482842fb643)), closes [#58](https://github.com/jpshackelford/ohtv/issues/58)
* Use agent-provided summary in action extraction ([#74](https://github.com/jpshackelford/ohtv/issues/74)) ([73afe1a](https://github.com/jpshackelford/ohtv/commit/73afe1a483c2a62b78281fee4b53c482842fb643))


### Bug Fixes

* add context_level to skip cache for proper retry at higher levels ([2807e64](https://github.com/jpshackelford/ohtv/commit/2807e64c575297f8b3a460dd3a369f151da2bc23)), closes [#60](https://github.com/jpshackelford/ohtv/issues/60)
* add context_level to skip cache for proper retry at higher levels ([#69](https://github.com/jpshackelford/ohtv/issues/69)) ([2807e64](https://github.com/jpshackelford/ohtv/commit/2807e64c575297f8b3a460dd3a369f151da2bc23))
* auto-promote context level for worker conversations ([#59](https://github.com/jpshackelford/ohtv/issues/59)) ([32498ac](https://github.com/jpshackelford/ohtv/commit/32498ac61ee0b47f2a02f2c69fdf025c2a36fbda))
* auto-promote context level for worker conversations ([#59](https://github.com/jpshackelford/ohtv/issues/59)) ([#66](https://github.com/jpshackelford/ohtv/issues/66)) ([32498ac](https://github.com/jpshackelford/ohtv/commit/32498ac61ee0b47f2a02f2c69fdf025c2a36fbda))
* **cache:** alias auto-promoted context_level so re-runs hit the cache ([#129](https://github.com/jpshackelford/ohtv/issues/129)) ([29c3b70](https://github.com/jpshackelford/ohtv/commit/29c3b70569128d6bbbe7af90c22bfb2856a9b3ba))
* database cleanup for orphaned embeddings and duplicate conversations ([34e8ce0](https://github.com/jpshackelford/ohtv/commit/34e8ce0bd121fa6ddb6b3b63845fd5c7b1581be5))
* embedding progress bar displays remaining count and ETA ([#55](https://github.com/jpshackelford/ohtv/issues/55)) ([0215fb0](https://github.com/jpshackelford/ohtv/commit/0215fb00b30c4adcc3c570977f3acf543b4f6e69))
* handle detailed analysis format in embedding generation and clean up orphaned cache ([c97d9db](https://github.com/jpshackelford/ohtv/commit/c97d9db3fa9cf80147e2f35d5b1b1fe44aa84179))
* improve embedding progress bar with remaining count and ETA ([#55](https://github.com/jpshackelford/ohtv/issues/55)) ([0215fb0](https://github.com/jpshackelford/ohtv/commit/0215fb00b30c4adcc3c570977f3acf543b4f6e69)), closes [#45](https://github.com/jpshackelford/ohtv/issues/45)
* **investigator:** add missing name field to tool responses and improve UX ([7eb90f3](https://github.com/jpshackelford/ohtv/commit/7eb90f374278610cbe75520399174d388319b35b))
* **investigator:** fix tool responses and improve investigation UX ([#70](https://github.com/jpshackelford/ohtv/issues/70)) ([7eb90f3](https://github.com/jpshackelford/ohtv/commit/7eb90f374278610cbe75520399174d388319b35b))
* **investigator:** update tool_call attribute access for SDK v1.21 ([#68](https://github.com/jpshackelford/ohtv/issues/68)) ([4269995](https://github.com/jpshackelford/ohtv/commit/426999591e6187b892f0435909ad12d2a41abf01))
* **list:** date filters imply --all (no pagination) ([a6ba9cd](https://github.com/jpshackelford/ohtv/commit/a6ba9cde5ba8abd75c5f5dfa011573f1ed9d67aa))
* normalize numeric context levels in batch mode ([#61](https://github.com/jpshackelford/ohtv/issues/61)) ([3da17e2](https://github.com/jpshackelford/ohtv/commit/3da17e234bea919cacbf248ad72b74fc09950627))
* **prompts:** add refs_display to display schemas ([#30](https://github.com/jpshackelford/ohtv/issues/30)) ([b3faa67](https://github.com/jpshackelford/ohtv/commit/b3faa679f1b63fbe55de2423e0fbceb98d29bb3a))
* Sort gen objs batch output by timestamp instead of completion order ([a2a962d](https://github.com/jpshackelford/ohtv/commit/a2a962d76c34c52ee4c80f5286fb8c38ecb480fc)), closes [#64](https://github.com/jpshackelford/ohtv/issues/64)
* summary command now checks cache before confirmation prompt ([c6626ea](https://github.com/jpshackelford/ohtv/commit/c6626ea7ca44b56edaa04270292c6937bdba6da3))
* summary progress bar shows only uncached conversations ([4994dab](https://github.com/jpshackelford/ohtv/commit/4994dab2fb4808de1271d00d4d182a24da1b977b))
* **sync:** sort by updated_at DESC in reset_to_n_newest ([#107](https://github.com/jpshackelford/ohtv/issues/107)) ([470a8c0](https://github.com/jpshackelford/ohtv/commit/470a8c0dc346d1b117c0b62c013064490f8afab1))
* update prompt display schemas to match 4-column layout from PR [#56](https://github.com/jpshackelford/ohtv/issues/56) ([e796064](https://github.com/jpshackelford/ohtv/commit/e79606415fc5c40d86fb732818abb10f5755aeb5))
* use needs_processing instead of non-existent is_complete method ([2669702](https://github.com/jpshackelford/ohtv/commit/2669702f5006b77908f30728a6f82a0e490a9f8f))

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
