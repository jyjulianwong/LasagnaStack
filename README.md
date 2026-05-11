# LasagnaStack

<img src="docs/lasagna.png" alt="LasagnaStack" width="180" />

An AI pipeline that turns raw video clips into an editable CapCut project for short-form reel editing.

It is as simple as:

```bash
python -m lasagnastack make ./my_clips/ --out ./my_capcut_draft/
```

where...

`./my_clips/`: a folder of raw video clips in MP4/MOV format + one `.txt` creator brief.  
`./my_capcut_draft/`: a CapCut draft folder, ready to open in CapCut Desktop.

The pipeline runs in six sequential stages: **ingest** (uses ffmpeg) → **analyse** (uses LLM) → **direct** (uses LLM) → **critique loop** (uses LLM) → **enhance** (uses LLM) → **render** (uses pyCapCut).

Each stage is a subclass of the `Stage` abstract base class (`base.py`). Adding, removing, or reordering stages requires only editing the `stages` list in `ReelPipeline`. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full architecture guide.

## Get started with development

1. Clone the repository.

```bash
git clone https://github.com/jyjulianwong/LasagnaStack.git
```

2. Verify that you have a compatible Python version installed on your machine.

```bash
python --version
```

3. Install [uv](https://github.com/astral-sh/uv) (used as the package manager for this project).

4. Install the development dependencies.

```bash
cd LasagnaStack/
uv sync --all-groups
uv run pre-commit install
```

## Set up environment

Copy `.env.sample` to `.env` and fill in your values:

```bash
cp .env.sample .env
```

`.env` is gitignored. Values set in the shell environment take precedence over `.env`.

## Authentication

Get a Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and add it to your `.env`:

```
GEMINI_API_KEY=your-key-here
```

## Run the pipeline

Prepare an input folder containing your MP4/MOV clips and exactly one `.txt` brief file, then run:

```bash
uv run python -m lasagnastack make ./my_clips/ --out ./drafts/reel_2025_05_05
```

The pipeline pauses for confirmation between each stage. To skip all prompts:

```bash
uv run python -m lasagnastack make ./my_clips/ --out ./drafts/reel_2025_05_05 --yes
```

Full CLI reference:

```
usage: lasagnastack make [-h] --out OUTPUT_DIR [--skill SKILL_FILE] [--yes]
                         [--critique-max-retries N] [--ingest-max-workers N]
                         [--analyse-max-workers N] INPUT_DIR

positional arguments:
  INPUT_DIR                     Folder containing clips and brief .txt

options:
  --out OUTPUT_DIR              Destination for the CapCut draft and working files
  --skill SKILL_FILE            Markdown skill file injected into the direct, critique,
                                and enhance prompts (optional)
  --yes, -y                     Auto-confirm all stage prompts
  --critique-max-retries N      Critique loop cap (default: 2)
  --ingest-max-workers N        Parallel worker processes for Stage 1 — ingest (default: 2)
  --analyse-max-workers N       Concurrent LLM calls for Stage 2 — analyse (default: 4)
```

## Open the draft in CapCut Desktop (macOS)

If CapCut Desktop is installed, the pipeline automatically:

1. Detects `~/Movies/CapCut/User Data/`
2. Copies **all** `.mp4`/`.mov` files from your input folder into the CapCut draft folder — including clips not used on the timeline — so they are immediately available in CapCut's import panel
3. Rewrites the timeline clip paths in `draft_info.json` to point to the copied files
4. Registers the draft in `root_meta_info.json` so it appears on the CapCut home screen straight away

Open CapCut Desktop after the pipeline finishes — the draft will appear on the home screen under your local projects with all media already linked. Drafts are named **LasagnaStack - Reel Name** and use that same string as the folder name so they are easy to identify among existing projects.

If CapCut is not installed, the draft is written to `<output_dir>/draft/LasagnaStack - {reel_name}/` and you can copy it manually.

> This has been tested with CapCut Desktop 8.5.0 on macOS Sequoia 15.6.1. There may be issues with older versions or other operating systems.

## Track LLM costs with MLflow

Every pipeline run is automatically traced with [MLflow](https://mlflow.org). Each Gemini API call is recorded as a span (prompt, response, token counts, latency, and estimated USD cost). Session-level totals are written to the run when the pipeline finishes.

**1. Start the MLflow server** (in a separate terminal, before running the pipeline):

```bash
mlflow server --host 127.0.0.1 --port 5001
```

> **macOS note:** port 5000 is reserved by AirPlay Receiver. Use 5001 or higher.

**2. Add the tracking variables to `.env`:**

```
MLFLOW_TRACKING_URI=http://localhost:5001
MLFLOW_EXPERIMENT_NAME=lasagnastack
```

**3. Run the pipeline as normal.** Open `http://localhost:5000` in your browser to watch live.

- **Traces tab** — spans appear in real time as stages progress. Each trace has three levels: the top-level pipeline span (`ReelPipeline.run`), a per-stage span (e.g. `AnalyseStage.run`), and individual LLM call spans (`GeminiClient._call_api`) nested inside.
- **Metrics tab** — `total_input_tokens`, `total_output_tokens`, `total_cost_usd`, and `llm_call_count` are written once the run completes.

Runs are named `lasagnastack-{brief_stem}-{4-char-id}` and tagged with the model, reel name, and `critique_max_retries`.

> **No server?** Set `MLFLOW_TRACKING_URI=mlruns` to write results to a local folder instead, then view them with `mlflow ui`.

## Configuration

| Parameter | How to set | Default |
|---|---|---|
| Gemini API key | `GEMINI_API_KEY` env var (required) | — |
| LLM model | `LASAGNASTACK_LLM_MODEL` env var | `gemini/gemini-2.5-flash` |
| Skill file | `--skill` CLI flag | — |
| Critique loop cap | `--critique-max-retries` CLI flag | `2` |
| Stage 1 worker processes | `--ingest-max-workers` CLI flag | `2` |
| Stage 2 concurrent LLM calls | `--analyse-max-workers` CLI flag | `4` |
| Output resolution | `_TARGET_WIDTH` / `_TARGET_HEIGHT` in `src/lasagnastack/stages/ingest.py` | `480×854` |

Example — run with a different model:

```bash
LASAGNASTACK_LLM_MODEL=gemini/gemini-2.5-pro \
  uv run python -m lasagnastack make ./my_clips/ --out ./drafts/test
```

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for four annotated diagrams covering the pipeline data flow, the Stage 4 critique loop, the Stage 6 render + CapCut export, and the extensibility model.

## Get started with Jupyter notebooks

1. Once the above setup is complete, set up a Python kernel.

```bash
source .venv/bin/activate
python -m ipykernel install --user --name=lasagnastack
```

2. Refer to the following common commands.

```bash
jupyter kernelspec list
jupyter kernelspec uninstall lasagnastack
```

3. Start the Jupyter server.

```bash
jupyter lab
```

## This repo is cool because...

- The pipeline is modularlised into stages, with each stage being responsible for transforming the global state of the pipeline run (similar to Google ADK). It is easy to add, remove, or reorder stages.
- Human-in-the-loop is deeply integrated in the design, with each stage prompting the user for confirmation before proceeding to the next stage.
- Prompt caching is enabled to avoid unnecessary LLM calls to reduce latency and cost.
- The tool is deeply integrated with its host machine. It auto-detects CapCut Desktop, copies all source media (timeline clips and unused footage) into the draft folder, rewrites paths in `draft_info.json`, and registers the project in CapCut's local project registry — so the draft opens in CapCut with no missing-media errors, no manual steps, and all your raw clips already in the import panel.