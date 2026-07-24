# Autocutter — key file interview sheet

Quick reference for the main frontend and backend modules. Use this to answer “what does this do?” live.

---

## Frontend

### `frontend/src/pages/UploadPage.tsx`

**What is its responsibility?**  
Landing page for a new job: pick a video, set optional target length / focus, kick off upload + processing, then navigate to the editor when the pipeline finishes.

**What state does it manage?**  
Local React state only: `file`, `targetMinutes`, `focus`, `busy`, `phase` (`idle` | `upload` | `process`), SSE `progress` / `step` / `message`, and `error`.

**What data does it receive?**  
No route params. User input via `FileDrop` and form fields. SSE progress events from `processProject`.

**What does it return or render?**  
The upload UI: branding, `FileDrop` (with client thumbnail), target/focus fields, `ProgressBar` while busy, Process button. On success navigates to `/projects/{project_id}`.

---

### `frontend/src/pages/EditorPage.tsx`

**What is its responsibility?**  
Project editor shell: load scored + edit decision, show video player + timeline, own Save & Export (PATCH segments then POST export SSE).

**What state does it manage?**  
`scoredSegments`, `segments` (`EditSegment[]` — source of truth for edits), `targetMinutes`, `focus`, `loading` / `error`, plus export modal state (`exportOpen`, `exportPhase`, `cleanAudio`, `resolution`, progress fields). Holds a `VideoPlayer` ref for seek.

**What data does it receive?**  
`projectId` from the URL (`useParams`). Loads `GET /projects/{id}/segments` (scored + edit_decision + meta). Export options from `ExportModal`.

**What does it return or render?**  
Header, `VideoPlayer`, `TimelineEditor` (or loading), `ExportModal`. Passes `setSegments` / seek / export handlers into children.

---

### `frontend/src/components/TimelineEditor.tsx`

**What is its responsibility?**  
Interactive rough-cut UI: horizontal kept timeline (dnd-kit reorder, trim handles), collapsed cut list, duration vs target, Save & Export button.

**What state does it manage?**  
UI-only: `activeId` (drag overlay), `cutOpen`, `trimming` (live trim tooltip). Segment data is controlled via props (`segments` / `onChange`).

**What data does it receive?**  
Props: `segments`, `targetMinutes`, `onChange`, `onSeek`, `onSaveAndExport`, `exporting`. Uses helpers from `lib/segments.ts` (`reorderKept`, `trimSegment`, `toggleKeep`, etc.).

**What does it return or render?**  
Timeline card: kept blocks (width ∝ trim length), cut accordion, counters, Save & Export CTA. Does not call the API itself.

---

### `frontend/src/api.ts`

**What is its responsibility?**  
HTTP client for the FastAPI backend: upload, process/export SSE readers, segments fetch/patch, URL helpers. No UI.

**What state does it manage?**  
None (stateless functions). Parses SSE streams until `complete` / `error`.

**What data does it receive?**  
`File` for upload; `projectId` + options for process/export; `ApiEditSegment[]` for PATCH; optional `AbortSignal`.

**What does it return or render?**  
Promises: `{ project_id }`, `ProgressEvent`, `SegmentsResponse`, void on save. Builds `/api/...` paths (`videoUrl`, `exportDownloadUrl`). Renders nothing.

---

### `frontend/src/lib/segments.ts`

**What is its responsibility?**  
Pure domain helpers for edit decisions: init/merge from scored API data, toggle/reorder/trim, duration math, map client model → API (`trim_in` / `trim_out` / `order`).

**What state does it manage?**  
None — pure functions, no React.

**What data does it receive?**  
`ScoredSegment[]`, `ApiEditSegment[]` / `EditSegment[]`, ids, trim edges, reorder active/over ids.

**What does it return or render?**  
New `EditSegment[]` arrays, durations, `ApiEditSegment[]` via `toApiEditDecision`. Renders nothing.

---

## Backend

### `backend/main.py`

**Why does this file exist?**  
FastAPI app entrypoint: HTTP routes, request validation (Pydantic), CORS, SSE wiring. Thin controller — heavy work is delegated.

**What's its role in the pipeline?**  
Does not run Whisper/Claude itself. Exposes:
- `POST /projects` — upload  
- `POST /projects/{id}/process` — SSE around `run_process`  
- `GET/PATCH .../segments` — read/write `edit_decision.json`  
- `POST .../export` — validate decision then SSE around `run_export`  
- video + export download  

`_sse_from_worker` runs a blocking worker in a thread and streams progress dicts as SSE.

**Which other modules does it interact with?**  
`backend.pipeline.run_process`, `backend.export` (`run_export`, `validate_edit_decision`, `load_edit_decision`), `backend.storage` (paths, meta, video), `autocutter.names.video_slug`.

---

### `backend/pipeline.py`

**Why does this file exist?**  
Orchestrates one project’s process job with progress callbacks for SSE.

**What's its role in the pipeline?**  
`run_process`: extract audio → Whisper (`transcribe`) → Claude scoring (`analyze_transcript`) → `select_segments` → write `edit_decision.json` + update `meta.json`. Honors caches unless `force`; resolves Whisper/API key settings.

**Which other modules does it interact with?**  
`autocutter.extract_audio`, `autocutter.transcribe`, `autocutter.analyze`, `autocutter.select_segments`, `backend.storage` (paths, meta, `build_initial_edit_decision`). Called from `main.py` process endpoint.

---

### `autocutter/analyze.py`

**Why does this file exist?**  
LLM scoring layer: turn transcript segments into interest scores + tags (+ optional theme).

**What's its role in the pipeline?**  
`analyze_transcript` chunks ~12 min windows, calls Anthropic with system/user prompts, parses JSON scores, merges by id, writes `scored_segments.json`. Does **not** decide keep/cut (that’s `select_segments`).

**Which other modules does it interact with?**  
Anthropic SDK. Invoked by `backend.pipeline` (and CLI). Output consumed later by select + frontend via scored file / API.

---

### `autocutter/transcribe.py`

**Why does this file exist?**  
Speech-to-text with faster-whisper and natural segment boundaries.

**What's its role in the pipeline?**  
`transcribe`: load model (CPU/int8, env overrides for model / word timestamps), run Whisper, regroup words into pause/sentence segments (`segments_to_natural_boundaries`), write `transcript.json` and optionally `words.json` for filler trim. First content stage after audio extract.

**Which other modules does it interact with?**  
`faster_whisper`, `autocutter` paths (`AUTOCUTTER_MODELS`). Called from `backend.pipeline` and CLI. Downstream: `analyze.py`.

---

### `backend/export.py`

**Why does this file exist?**  
Turn the saved edit decision into a downloadable MP4 via ffmpeg (web path; separate from CLI FCPXML).

**What's its role in the pipeline?**  
After human edit (or initial decision): validate trims/order → optional filler micro-cuts (`TRIM_FILLER_WORDS`) → optional resolution scale → `filter_complex` trim/atrim/concat (+ optional audio cleanup) → encode (`libx264` / AAC) → `export.mp4`. Emits SSE progress.

**Which other modules does it interact with?**  
`backend.storage` (video, edit decision, export path, meta), `autocutter.filler`, system `ffmpeg`/`ffprobe`. Called from `main.py` export endpoint. Does not call Whisper or Anthropic.

---

## End-to-end mental model

```
UploadPage → api.createProject / processProject
                ↓
            main.py → pipeline.run_process
                ↓
         extract → transcribe → analyze → select → edit_decision.json
                ↓
EditorPage ← api.fetchSegments
                ↓
TimelineEditor edits segments (client)
                ↓
api.patchSegments + exportProject
                ↓
main.py → export.run_export → export.mp4
```
