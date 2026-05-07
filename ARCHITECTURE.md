# Architecture

Four diagrams covering the pipeline end-to-end, the critique loop, the render stage, and the extensibility model.

---

## 1 · Pipeline overview

Each stage transforms the shared `PipelineState` and writes its output to disk before pausing for a human confirmation prompt (skippable with `--yes`).

```mermaid
flowchart TD
    INPUT(["📂 Input folder\nMP4 / MOV clips  +  brief.txt"])

    S1["**Stage 1 · Ingest**\nffmpeg  ·  PySceneDetect\n──────────────────────────\nNormalise every clip to 720 × 1280 H.264\nDetect scene-cut timestamps"]
    S2["**Stage 2 · Analyse**\nGemini Files API\n──────────────────────────\nUpload normalised clips, request structured\nper-segment metadata (shot type, score, crop safety …)\nResponses cached on disk by file SHA-256"]
    S3["**Stage 3 · Direct**\nGemini generate()\n──────────────────────────\nSend all segment data + brief in a single call\nReceive an ordered CutList as structured JSON"]
    S4["**Stage 4 · Critique Loop**\nGemini generate()\n──────────────────────────\nCritic LLM reviews CutList against 8 criteria\nRevises and re-submits up to N times until approved"]
    S5["**Stage 5 · Render**\npyCapCut\n──────────────────────────\nAssemble 9 : 16 draft from original HD clips\nAuto-copy to CapCut Desktop if installed"]

    OUTPUT(["🎬 CapCut Desktop\n(draft auto-imported)"])
    DISK[("output_dir/\nnormalised/   inventories/\ncut_list.json   critique/\ndraft/")]

    INPUT --> S1
    S1 -->|"list[NormalisedClip]   👤"| S2
    S2 -->|"list[ClipInventory]   👤"| S3
    S3 -->|"CutList   👤"| S4
    S4 -->|"CutList   👤"| S5
    S5 --> OUTPUT
    S1 & S2 & S3 & S4 & S5 -. writes .-> DISK
```

> **👤** = human confirmation prompt between stages. All prompts are skipped when `--yes` is passed.

---

## 2 · Stage 4 — Critique loop

The critic LLM checks eight criteria (duration, cut count, hook-first, shot variety, crop safety, aesthetics, story arc, brief alignment). If any fail, it returns a corrected `cut_list_v2` and the loop repeats. The loop ships the last cut list once the retry cap is hit.

```mermaid
flowchart TD
    START(["CutList from Stage 3"])

    ZERO{"max_retries = 0?"}
    SKIP(["Return CutList unchanged\n(critique disabled)"])

    CRITIQUE["Send CutList + inventories + brief\nto critic LLM"]
    WRITE["Write critique/iteration_N.json"]
    VERDICT{"verdict?"}

    UPDATE["CutList ← cut_list_v2"]
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

## 3 · Stage 5 — Render & CapCut export

`run()` iterates over every `Cut` in order, assembling a `ScriptFile` timeline. After saving, it detects CapCut on the local machine and, if found, copies source clips into the draft folder (so CapCut finds all media without re-linking) and rewrites the absolute paths in `draft_content.json`.

```mermaid
flowchart TD
    START(["Approved CutList"])

    INIT["Create pyCapCut DraftFolder\nfolder: lasagnastack_{slug}\ndisplay name: LasagnaStack - {restaurant}"]

    MATERIAL["VideoMaterial\nprobe source clip with pymediainfo\n(original HD — not normalised)"]
    CROP["Compute CropSettings\n9:16 portrait crop from landscape source\ncenter / left_third / right_third + offset_x nudge"]
    CLAMP["Clamp out-point to clip duration\n(guards against LLM over-shoot)"]
    SEGMENT["VideoSegment\n(source_timerange, speed, CropSettings)"]

    TRANS{"transition_out =\nfade or dissolve?"}
    ADD_TRANS["Add 叠化 cross-dissolve\nto preceding segment"]

    CAP{"Cut.caption set?"}
    ADD_CAP["TextSegment on captions track\ntransform_y positions top / center / bottom"]

    MORE{"more cuts?"}

    SAVE["script.save()\n→ draft_content.json"]

    DETECT{"CapCut found at\n~/Movies/CapCut/User Data/?"}

    EXPORT["Copy unique source clips\ninto CapCut draft folder\nRewrite 'path' fields in draft_content.json\nCopy draft → com.lveditor.draft/"]

    CC(["🎬 CapCut Desktop\n(draft + media self-contained)"])
    LOCAL(["📁 output_dir/draft/\n(manual import needed)"])

    START --> INIT --> MATERIAL --> CROP --> CLAMP --> SEGMENT --> TRANS
    TRANS -->|yes| ADD_TRANS --> CAP
    TRANS -->|no| CAP
    CAP -->|yes| ADD_CAP --> MORE
    CAP -->|no| MORE
    MORE -->|yes| MATERIAL
    MORE -->|no| SAVE
    SAVE --> DETECT
    DETECT -->|yes| EXPORT --> CC
    DETECT -->|no| LOCAL
```

---

## 4 · Extensibility model

`Stage` and `Pipeline` are abstract base classes. `PipelineState` is an immutable dataclass — each stage receives it and returns a new copy with its field populated. `LLMClient` is a provider-agnostic interface; swap it by subclassing and injecting an instance.

```mermaid
classDiagram
    class Pipeline {
        <<abstract>>
        +stages() list[Stage]
        +run(state, auto_confirm) PipelineState
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
        +max_critique_retries int
        +normalised_clips list[NormalisedClip]
        +inventories list[ClipInventory]
        +cut_list CutList
        +draft_path Path
    }

    class LLMClient {
        <<abstract>>
        +generate(prompt, schema) BaseModel
        +generate_with_video(path, prompt, schema) BaseModel
    }

    class ReelPipeline {
        +stages() list[Stage]
    }

    class GeminiClient {
        +generate()
        +generate_with_video()
    }

    class IngestStage
    class AnalyseStage
    class DirectStage
    class CritiqueStage
    class RenderStage

    Pipeline  <|-- ReelPipeline
    Stage     <|-- IngestStage
    Stage     <|-- AnalyseStage
    Stage     <|-- DirectStage
    Stage     <|-- CritiqueStage
    Stage     <|-- RenderStage
    LLMClient <|-- GeminiClient

    ReelPipeline  "1" o-- "5" Stage       : stages
    Pipeline           --> PipelineState  : transforms
    AnalyseStage       --> LLMClient      : uses
    DirectStage        --> LLMClient      : uses
    CritiqueStage      --> LLMClient      : uses
```

> To **add a stage**: subclass `Stage`, implement `run()` and `completion_message()`, then insert an instance into `ReelPipeline.stages`.
> To **swap the LLM provider**: subclass `LLMClient` and pass an instance to `ReelPipeline(client=…)`.
