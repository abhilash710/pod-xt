# PRD: Add UI layer to PodX

## Context

### Problem

Non‑technical users (and technical users who dislike memorizing flags) can’t comfortably run PodX. The CLI requires terminal fluency, remembering options, and interpreting logs. This blocks broader adoption and slows down those who just want to get to the knowledge, wisdom and actionable nuggets within the transcripts, summaries, and exports.

### Solution

A local web UI (called "PodX Studio") that lets users paste a podcast page/RSS/YouTube URL, choose a preset (or open Advanced), and click **Run**. It orchestrates the existing PodX pipeline (fetch → transcode → transcribe → optional diarize/align → analyze → export), shows stage progress, and culminates in a **Completion Panel** with per‑stage checkmarks. On success it shows a button to "Show in Finder" (to display where the outputs are located) and—if Notion is connected—a link to "**View in Notion"**. On failure it pinpoints the failing stage with a red ×. Zero‑install flow via `podx ui`.

## Product Spec

### Value proposition

* Get to the content and learnings you were after
* No terminal or flags; sensible defaults with optional power‑controls.
* Clear progress for each step + actionable errors

### User Journey

1. **Landing**: Single field (“Paste URL”), **Recommended** preset selected, **Advanced** collapsed.
2. **Validation**: URL type auto‑detected (show/episode/RSS/YouTube); **Run** enabled when valid.
3. **Run Orchestration**: Progress panel shows stages (Fetch, Transcode, Transcribe, Diarize, Analyze, Export) with status chips; **Cancel** available.
4. **Results**: **Completion Panel** with per‑stage checkmarks; on success, **Show in Finder** (opens outputs) and—if Notion is connected—**View in Notion**; transcript viewer (time‑codes; speakers if diarized), summary/insights pane, export buttons. On failure, the failing stage is marked with a red × and the UI offers **Retry from this stage** and **Copy debug CLI**.
5. **History**: Recent runs list with status; **Re‑Run** action; **Save as Preset** from the run summary.

### User Stories

1. **Paste‑and‑Go Run** — As a new user, I can paste a valid URL (podcast page, RSS, YouTube) and start a run with the **Recommended** preset in ≤2 clicks.
2. **Advanced Options** — As a power user, I can open an **Advanced** drawer to toggle diarization, model/engine, alignment, and analysis.
3. **Progress & Safe Stop** — As a user, I can see per‑stage progress and cancel without corrupting outputs.
4. **Transcript & Speaker View** — As a user, I can read/search a time‑coded transcript with speaker labels when diarization is enabled.
5. **Exports** — As a user, I can export results in **txt, json, srt, vtt, md** or a full zip.
6. **Recent Runs & Re‑Run** — As a returning user, I can view recent runs and re‑run with identical settings.
7. **Presets** — As a user, I can save/apply a named set of options.
8. **Actionable Errors & Debug CLI** — On failure, I see a readable error and a one‑click copy of the equivalent CLI command (secrets redacted).
9. **Resource Guardrails** — The app prevents runaway usage (concurrency/length caps) with clear messaging.
10. **Zero‑Install Launch** — I can start the UI via a single command that opens my browser.


### Acceptance Criteria

* Paste‑and‑Go: Progress view appears ≤2s after clicking **Run**; successful runs provide transcript + summary artifacts.
* Advanced Options: All toggles map 1:1 to internal flags; run summary lists chosen options.
* Safe Stop: Cancel halts downstream stages; run is labeled **Canceled**; partial outputs retained.
* Transcript & Search: Renders within 2s; search returns matches across ≥10k tokens; diarization shows speaker labels when enabled.
* Exports: Buttons produce correctly typed files; zip contains expected structure and non‑zero sizes.
* History & Re‑Run: Last 20 runs visible; re‑run duplicates parameters.
* Presets: Create/apply/delete works; applying updates the advanced pane.
* Completion Panel: On success, all stages show green checkmarks; **Show in Finder** is present; if Notion is connected, **View in Notion** opens the created page.
* Errors: Error panel shows stage, human‑readable message, redacted snippet; **Copy debug CLI** matches options; **Retry from this stage** is available.
* Resource Caps: 1 active run (default) enforced; >max audio length shows pre‑run validation error.
* Zero‑Install: `podx ui` boots server, opens browser, and serves UI on localhost.

### Definition of Done
* Completion Panel: Green check per stage on success; red × on failure with Retry from this stage + Copy debug CLI.

* Success actions: Show in Finder opens outputs; if Notion is connected, View in Notion opens the created page.

* History: Last 20 runs listed; Re-Run reproduces prior parameters.

* Quality gates: Build/test/lint clean; `/health` server smoke test; one e2e for Paste-and-Go; all UI behind `ui_enabled`; no changes to CLI semantics.

### Out of Scope

* Login
* Multi‑user auth, roles, and billing.
* Scheduling/cron or distributed queue processing.
* In‑browser/on‑device transcription without server/worker.
* New ML models/features beyond current PodX capabilities.
* No multi-source batching, no auth, no scheduler/queue, no model switching UI beyond the advanced toggles already listed.

## Technical Details

### Guardrails

* Read‑only defaults: No config mutation unless saving a preset.
* Secrets: Never display tokens; keep server‑side; redact logs.
* Filesystem: Write outputs only into PodX’s standard output directory.
* Feature Flag: `ui_enabled` controls exposure; CLI remains source of truth.
* Validation: Sanitize URLs; fetch RSS server‑side to avoid CORS/credential leakage.
* Observability: Per‑run IDs, stage logs, redactions for PII; copyable debug CLI on failure.

### Edge Cases

* Invalid/unsupported URLs (bad RSS, private YouTube, geo‑blocked audio) → friendly error + debug CLI.
* Long media (>limit) → pre‑run validation message with guidance to trim or adjust limit.
* Network loss mid‑run → resumable or clearly canceled state with retry affordance.
* Diarization/model unavailable → skip gracefully with notice; continue remaining stages.
* Duplicate runs on same URL → allow but show deduped artifacts in history.

### Constraints

* **Reuse PodX pipeline**: Call Python commands/services; don’t fork logic.
* **Thin web layer**: Minimal API to start runs, stream progress, fetch artifacts; local first.
* **Performance**: UI adds ≤5% overhead vs equivalent CLI invocation.
* **Compatibility**: No breaking changes to existing CLI flags; advanced pane maps 1:1.
* **Portability**: Works offline/local; no mandatory cloud services.

### Code Etiquette (Test Cases, Branching, Comments)

* **Branching**: `feature/podx-studio-v1` with small PRs; protect main; require CI green.
* **Tests**: Add e2e for Paste‑and‑Go, Cancel, Diarized export, and Error/Debug CLI; unit tests for URL validation and flag mapping.
* **Lints/Format**: Enforce existing formatter/linter; PR must be clean.
* **Comments/Docs**: Each new module top‑comment: purpose, inputs, outputs; PR includes a short ship note and a demo script.
* **Flags**: All UI‑invoked features live behind `ui_enabled`; include a rollback note in the PR.

### Working Mode
* Plan first: Propose the minimal architecture and interfaces in a concise plan mapped to this PRD. I approve the plan; you choose files/APIs.


* Single PR: Implement end-to-end in one PR. Create the PR early with the approved plan in the description.

* Self-service interfaces: Invent any internal interfaces you need; document briefly in the PR.

* No hand-holding: Do not ask me to define file lists, endpoints, or JSON contracts.