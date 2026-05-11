# Architecture

Five diagrams covering the pipeline end-to-end, the critique loop, the enhance stage, the render stage, and the extensibility model.

---

## 1 · Pipeline overview

Each stage transforms the shared `PipelineState` and writes its output to disk before pausing for a human confirmation prompt (skippable with `--yes`).

```mermaid
flowchart TD
    INPUT(["📂 Input folder\nMP4 / MOV clips  +  brief.txt"])

    S1["**Stage 1 · Ingest**\nffmpeg  ·  PySceneDetect\n──────────────────────────\nNormalise every clip to 480 × 854 H.264\nDetect scene-cut timestamps"]
    S2["**Stage 2 · Analyse**\nGemini Files API\n──────────────────────────\nUpload normalised clips, request structured\nper-segment metadata (shot type, score, crop safety …)\nResponses cached on disk by file SHA-256"]
    S3["**Stage 3 · Direct**\nGemini generate()\n──────────────────────────\nSend all segment data + brief in a single call\nReceive an ordered CutList as structured JSON"]
    S4["**Stage 4 · Critique Loop**\nGemini generate()\n──────────────────────────\nCritic LLM reviews CutList against 10 criteria\nRevises and re-submits up to N times until approved"]
    S5["**Stage 5 · Enhance**\nGemini generate()\n──────────────────────────\nAssign per-cut transitions, caption colours,\nborders, and entrance / exit animations\nTimeline overlay styling also resolved here"]
    S6["**Stage 6 · Render**\npyCapCut\n──────────────────────────\nAssemble 9 : 16 draft from original HD clips\nMerge ReelStyle styling into TextSegments\nAuto-copy to CapCut Desktop if installed"]

    OUTPUT(["🎬 CapCut Desktop\n(draft auto-imported)"])
    DISK[("output_dir/\nnormalised/   inventories/\ncut_list.json   critique/\nreel_style.json   draft/")]

    INPUT --> S1
    S1 -->|"list[NormalisedClip]   👤"| S2
    S2 -->|"list[ClipInventory]   👤"| S3
    S3 -->|"CutList   👤"| S4
    S4 -->|"CutList   👤"| S5
    S5 -->|"ReelStyle   👤"| S6
    S6 --> OUTPUT
    S1 & S2 & S3 & S4 & S5 & S6 -. writes .-> DISK
```

> **👤** = human confirmation prompt between stages. All prompts are skipped when `--yes` is passed.

---

## 2 · Stage 4 — Critique loop

The critic LLM checks ten criteria (duration, cut count, hook-first, shot variety, crop safety, aesthetics, story arc, brief alignment, caption timing bounds, overlay timing bounds). If any fail, it returns a corrected `cut_list_v2` and the loop repeats. The loop ships the last cut list once the retry cap is hit.

```mermaid
flowchart TD
    START(["CutList from Stage 3"])

    ZERO{"max_retries = 0?"}
    SKIP(["Return CutList unchanged\n(critique disabled)"])

    CRITIQUE["Send CutList + inventories + brief\nto critic LLM"]
    WRITE["Write critique/iteration_N.json"]
    VERDICT{"verdict?"}

    UPDATE["CutList ← cut_list_v2\nAppend issues to previous_issues log"]
    EXHAUSTED{"retries\nexhausted?"}

    APPROVED(["✅ Return approved CutList"])
    CAP(["⚠️ Return last CutList\n(cap reached — ships as-is)"])

    START --> ZERO
    ZERO -->|yes| SKIP
    ZERO -->|no| CRITIQUE
    CRITIQUE --> WRITE --> VERDICT
    VERDICT -->|approved| APPROVED
    VERDICT -->|revise| UPDATE --> EXHAUSTED
    EXHAUSTED -->|no| CRITIQUE
    EXHAUSTED -->|yes| CAP
```

---

## 3 · Stage 5 — Enhance

A single LLM call focused purely on visual styling — no footage re-analysis. The approved `CutList` (including any `overlays`) and the brief are sent; the model returns a `ReelStyle` that decorates every cut and overlay with transition choices, text colour, border, size, and entrance/exit animations. The `CutList` itself is never modified.

```mermaid
flowchart TD
    START(["Approved CutList\n+ brief.txt"])

    PROMPT["Build enhance prompt\n(cut list JSON + brief text)"]
    LLM["Gemini generate(ReelStyle)\ntemperature 0.5"]

    CUTS["cut_styles — one CutStyle per cut\n· transition_out: cut | dissolve\n· caption_effect (null if no caption):\n  color, bold, italic, size,\n  border_color / border_width,\n  animation_in, animation_out"]

    OVERLAYS{"overlays in\nCutList?"}
    OV_STYLES["overlay_styles — one OverlayStyle per overlay\n· overlay_index (0-based)\n· caption_effect (same fields)\n  fade_in / fade_out recommended\n  to blend across cut boundaries"]

    WRITE["Write reel_style.json"]
    OUT(["ReelStyle → PipelineState.reel_style"])

    START --> PROMPT --> LLM --> CUTS
    CUTS --> OVERLAYS
    OVERLAYS -->|yes| OV_STYLES --> WRITE
    OVERLAYS -->|no| WRITE
    WRITE --> OUT
```

---

## 4 · Stage 6 — Render & CapCut export

`run()` iterates over every `Cut` in order, assembling a `ScriptFile` timeline. For each cut it resolves transition and caption styling from `ReelStyle` (if present), falling back to the `CutList` values. After all cuts are placed, timeline `overlays` are rendered using absolute millisecond positions. After saving, it detects CapCut on the local machine and, if found, copies source clips into the draft folder and rewrites the absolute paths in `draft_info.json`.

```mermaid
flowchart TD
    START(["Approved CutList\n+ optional ReelStyle"])

    INIT["Create pyCapCut DraftFolder\nfolder + display name:\nLasagnaStack - {title} {YYYYMMDD_HHMMSS}"]

    MATERIAL["VideoMaterial\nprobe source clip with pymediainfo\n(original HD — not normalised)"]
    CROP["Compute ClipSettings\n9:16 portrait crop from landscape source\ncenter / left_third / right_third + offset_x nudge"]
    CLAMP["Clamp out-point to clip duration\n(guards against LLM over-shoot)"]
    SEGMENT["VideoSegment\n(source_timerange, speed, ClipSettings)"]

    TRANS{"ReelStyle transition_out\nor cut.transition_out =\nfade / dissolve?"}
    ADD_TRANS["Add 叠化 cross-dissolve\nto preceding segment"]

    CAP{"Cut.caption set?"}
    STYLE["Resolve CaptionEffect from ReelStyle\n(color → RGB, bold, italic, size,\nborder, animation_in / animation_out)"]
    ADD_CAP["TextSegment on captions track\ntransform_y positions top / center / bottom\nTextBorder and add_animation() applied"]

    MORE{"more cuts?"}

    OVERLAYS{"CutList.overlays\nnon-empty?"}
    ADD_OV["For each overlay:\nTextSegment at absolute timeline position\n(start_ms / end_ms → microseconds)\nend clamped to total reel duration\nOverlayStyle applied if present in ReelStyle"]

    SAVE["script.save() → draft_info.json\n_patch_platform() fixes OS fields"]

    DETECT{"CapCut found at\n~/Movies/CapCut/User Data/?"}

    EXPORT["Copy all input .mp4/.mov into draft folder\nRewrite 'path' fields in draft_info.json\nUpdate draft_meta_info.json (materials list)\nRegister draft in root_meta_info.json"]

    CC(["🎬 CapCut Desktop\n(draft + media self-contained)"])
    LOCAL(["📁 output_dir/draft/\n(manual import needed)"])

    START --> INIT --> MATERIAL --> CROP --> CLAMP --> SEGMENT --> TRANS
    TRANS -->|yes| ADD_TRANS --> CAP
    TRANS -->|no| CAP
    CAP -->|yes| STYLE --> ADD_CAP --> MORE
    CAP -->|no| MORE
    MORE -->|yes| MATERIAL
    MORE -->|no| OVERLAYS
    OVERLAYS -->|yes| ADD_OV --> SAVE
    OVERLAYS -->|no| SAVE
    SAVE --> DETECT
    DETECT -->|yes| EXPORT --> CC
    DETECT -->|no| LOCAL
```

---

## 5 · Extensibility model

`Stage` and `Pipeline` are abstract base classes. `PipelineState` is an immutable dataclass — each stage receives it and returns a new copy with its field populated. `LLMClient` is a provider-agnostic interface; swap it by subclassing and injecting an instance.

```mermaid
classDiagram
    class Pipeline {
        <<abstract>>
        +stages() list[Stage]
        +run(state, auto_confirm) PipelineState
        +_run_stage(stage, state) PipelineState
        +_mlflow_run_name(state) str
        +_mlflow_tags(state) dict
        +_log_mlflow_session_metrics(state) None
    }

    class Stage {
        <<abstract>>
        +run(state) PipelineState
        +completion_message(state) str
    }

    class PipelineState {
        +input_dir Path
        +output_dir Path
        +brief_path Path
        +critique_max_retries int
        +normalised_clips list[NormalisedClip]
        +inventories list[ClipInventory]
        +cut_list CutList
        +reel_style ReelStyle
        +draft_path Path
    }

    class LLMClient {
        <<abstract>>
        +generate(prompt, schema) BaseModel
        +generate_with_video(path, prompt, schema) BaseModel
    }

    class ReelPipeline {
        +stages() list[Stage]
        +_mlflow_run_name(state) str
        +_mlflow_tags(state) dict
        +_log_mlflow_session_metrics(state) None
    }

    class GeminiClient {
        +generate()
        +generate_with_video()
    }

    class IngestStage
    class AnalyseStage
    class DirectStage
    class CritiqueStage
    class EnhanceStage
    class RenderStage

    Pipeline  <|-- ReelPipeline
    Stage     <|-- IngestStage
    Stage     <|-- AnalyseStage
    Stage     <|-- DirectStage
    Stage     <|-- CritiqueStage
    Stage     <|-- EnhanceStage
    Stage     <|-- RenderStage
    LLMClient <|-- GeminiClient

    ReelPipeline  "1" o-- "6" Stage       : stages
    Pipeline           --> PipelineState  : transforms
    AnalyseStage       --> LLMClient      : uses
    DirectStage        --> LLMClient      : uses
    CritiqueStage      --> LLMClient      : uses
    EnhanceStage       --> LLMClient      : uses
```

> To **add a stage**: subclass `Stage`, implement `run()` and `completion_message()`, then insert an instance into `ReelPipeline.stages`.
> To **swap the LLM provider**: subclass `LLMClient` and pass an instance to `ReelPipeline(client=…)`.
> To **create a new pipeline**: subclass `Pipeline`, declare `stages`, and optionally override `_mlflow_run_name`, `_mlflow_tags`, and `_log_mlflow_session_metrics` — MLflow tracking (run, per-stage CHAIN spans, and post-run metrics) is inherited automatically.
