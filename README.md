# LasagnaStack

<img src="docs/lasagna.png" alt="LasagnaStack" width="180" />

An AI pipeline that turns raw video clips into an editable CapCut draft for short-form video and reel editing.

It is as simple as:

```bash
python -m lasagnastack make ./my_clips/ --out ./my_capcut_draft/
```

where...

`./my_clips/`: a folder of raw video clips in MP4/MOV format + one `.txt` creator brief.  
`./my_capcut_draft/`: a CapCut draft folder, ready to open in CapCut Desktop.

The pipeline runs in five sequential stages: **ingest** (uses ffmpeg) → **analyse** (uses LLM) → **direct** (uses LLM) → **critique loop** (uses LLM) → **render** (uses pyCapCut).

Each stage is a subclass of the `Stage` abstract base class (`base.py`). Adding, removing, or reordering stages requires only editing the `stages` list in `ReelPipeline`. See `CLAUDE.md` for the full architecture guide.

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
uv run python -m lasagnastack make ./my_clips/ --out ./drafts/restaurant_2025_05_05
```

The pipeline pauses for confirmation between each stage. To skip all prompts:

```bash
uv run python -m lasagnastack make ./my_clips/ --out ./drafts/restaurant_2025_05_05 --yes
```

Full CLI reference:

```
usage: lasagnastack make [-h] --out OUTPUT_DIR [--yes] [--max-critique-retries N] INPUT_DIR

positional arguments:
  INPUT_DIR                     Folder containing clips and brief .txt

options:
  --out OUTPUT_DIR              Destination for the CapCut draft and working files
  --yes, -y                     Auto-confirm all stage prompts
  --max-critique-retries N      Critique loop cap (default: 2)
```

## Open the draft in CapCut Desktop (macOS)

If CapCut Desktop is installed, the pipeline automatically:

1. Detects `~/Movies/CapCut/User Data/`
2. Copies your source clips into the CapCut draft folder (so all media is self-contained)
3. Rewrites the clip paths in `draft_content.json` to point to the copied files
4. Copies the draft into `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`

Open CapCut Desktop after the pipeline finishes — the draft will appear on the home screen under your local projects with all media already linked. Drafts are named **LasagnaStack - Restaurant Name** and their folders are prefixed `lasagnastack_` so they are easy to identify among existing projects.

If CapCut is not installed, the draft is written to `<output_dir>/draft/lasagnastack_{slug}/` and you can copy it manually.

## Configuration

| Parameter | How to set | Default |
|---|---|---|
| Gemini API key | `GEMINI_API_KEY` env var (required) | — |
| Gemini model | `LASAGNASTACK_MODEL` env var | `gemini-2.5-flash` |
| Critique loop cap | `--max-critique-retries` CLI flag | `2` |
| Output resolution | `_TARGET_WIDTH` / `_TARGET_HEIGHT` in `src/lasagnastack/stages/ingest.py` | `720×1280` |

Example — run with a different model:

```bash
LASAGNASTACK_MODEL=gemini-2.5-pro \
  uv run python -m lasagnastack make ./my_clips/ --out ./drafts/test
```

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

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for four annotated diagrams covering the pipeline data flow, the Stage 4 critique loop, the Stage 5 render + CapCut export, and the extensibility model.

## This repo is cool because...

- The pipeline is modularlised into stages, with each stage being responsible for transforming the global state of the pipeline run (similar to Google ADK). It is easy to add, remove, or reorder stages.
- Human-in-the-loop is deeply integrated in the design, with each stage prompting the user for confirmation before proceeding to the next stage.
- Prompt caching is enabled to avoid unnecessary LLM calls to reduce latency and cost.
- The tool is deeply integrated with its host machine. It auto-detects CapCut Desktop, copies source media into the draft folder, and rewrites all paths so the project opens in CapCut with no missing-media errors and no manual steps.