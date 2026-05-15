# LasagnaStack

<img src="docs/lasagna.png" alt="LasagnaStack" width="180" />

An AI pipeline that turns raw video clips into an editable CapCut project for short-form reel editing.

It is as simple as:

```bash
lasagnastack make ./my_clips/ --out ./my_output_folder/
```

where...

`./my_clips/`: an existing folder of raw video clips in MP4/MOV format + one `.txt` creator brief.  
`./my_output_folder/`: a folder created by the pipeline to store its output, including:
  - A copy of the AI-generated CapCut project folder that will already have been loaded into CapCut Desktop.
  - A `post_caption.txt` file that contains the AI-generated post caption for the reel.
  - Intermediate output files from each pipeline stage for debugging and logging.
  - Cached files from various pipeline stages for faster re-runs.

The pipeline runs in seven sequential stages: 
  - **ingest** (uses ffmpeg) → 
  - **analyse** (uses LLM APIs) → 
  - **direct** (uses LLM APIs) → 
  - **critique loop** (uses LLM APIs) → 
  - **enhance** (uses LLM APIs) → 
  - **render** (uses pyCapCut) → 
  - **post caption** (uses LLM APIs)

---

## For users...

### Installation

Install via Homebrew:

```bash
brew tap jyjulianwong/lasagnastack                                                                                                  
brew install lasagnastack
```

Install via PyPI:

```bash
pip install lasagnastack
```

### Authentication

You will need to provide your own API keys for the LLM APIs you use. The required API key depends on the value of `LSNSTK_LLM_MODEL`.

#### Gemini (e.g. `gemini/gemini-2.5-flash`)

Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and set it as an environment variable:

```bash
export LSNSTK_LLM_MODEL=gemini/gemini-2.5-flash
export LSNSTK_LLM_GEMINI_API_KEY=your-key-here
```

#### OpenRouter (e.g. `openrouter/deepseek/deepseek-v3.2`)

Get a key at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) and set these environment variables:

```bash
export LSNSTK_LLM_MODEL=openrouter/deepseek/deepseek-v3.2
export LSNSTK_LLM_OPENROUTER_API_KEY=your-key-here
```

> **NOTE:** Stage 2 (analyse) uploads video to the Gemini Files API and always requires `LSNSTK_LLM_GEMINI_API_KEY`, even when the other stages use an OpenRouter model.

### How to add skills

Skills are used to customise the pipeline to your own social media account's styles and branding, or use pre-written skills from marketplaces to cater for different types of reel content.

A skill is a Markdown (`.md`) file that contains the prompt templates for the direct, critique, and enhance stages. The skill file is injected into the prompt templates for the direct, critique, and enhance stages.

You can use your own skill file by passing the `--skill` CLI flag to the `make` command.

### How to use the CLI

```
usage: lasagnastack make [-h] --out OUTPUT_DIR [--skill SKILL_FILE] [--yes]
                         [--critique-max-retries N] [--ingest-max-workers N]
                         [--analyse-max-workers N] INPUT_DIR

positional arguments:
  INPUT_DIR                     Folder containing clips and brief .txt

options:
  --out OUTPUT_DIR              Destination for the CapCut draft and working files
  --skill SKILL_FILE            Path to Markdown skill file injected into the direct, 
                                critique, and enhance prompt templates (optional)
  --yes, -y                     Auto-confirm all stage prompts
  --critique-max-retries N      Maximum # of critique loop retries (default: 2)
  --ingest-max-workers N        Maximum # of parallel worker processes for `ingest` stage (default: 2)
  --analyse-max-workers N       Maximum # of concurrent LLM calls for `analyse` stage (default: 4)
```

### Opening the draft in CapCut Desktop (macOS)

If CapCut Desktop is installed, the pipeline automatically:

1. Detects `~/Movies/CapCut/User Data/`
2. Copies **all** `.mp4`/`.mov` files from your input folder into the CapCut draft folder — including clips not used on the timeline — so they are immediately available in CapCut's import panel
3. Rewrites the timeline clip paths in `draft_info.json` to point to the copied files
4. Registers the draft in `root_meta_info.json` so it appears on the CapCut home screen straight away

Open CapCut Desktop after the pipeline finishes — the draft will appear on the home screen under your local projects with all media already linked. Drafts are named **LasagnaStack - Reel Name** and use that same string as the folder name so they are easy to identify among existing projects.

If CapCut is not installed, the draft is written to `<output_dir>/draft/LasagnaStack - {reel_name}/` and you can copy it manually.

> This has been tested with CapCut Desktop 8.5.0 on macOS Sequoia 15.6.1. There may be issues with older versions or other operating systems.

---

## For developers...

### Get started with development

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

### Set up environment

Copy `.env.sample` to `.env` and fill in your values (see [Authentication](#authentication) above for the available variables):

```bash
cp .env.sample .env
```

`.env` is gitignored. Values set in the shell environment take precedence over `.env`.

### Run the pipeline

Prepare an input folder containing your MP4/MOV clips and exactly one `.txt` brief file, then run:

```bash
uv run python -m lasagnastack make ./my_clips/ --out ./drafts/reel_2025_05_05
```

The pipeline pauses for confirmation between each stage. To skip all prompts:

```bash
uv run python -m lasagnastack make ./my_clips/ --out ./drafts/reel_2025_05_05 --yes
```

### Configuration

| Parameter | How to set | Default |
|---|---|---|
| LLM model | `LSNSTK_LLM_MODEL` env. var. | `gemini/gemini-2.5-flash` |
| Gemini API key | `LSNSTK_LLM_GEMINI_API_KEY` env. var. (required for `gemini/` models and Stage 2) | — |
| OpenRouter API key | `LSNSTK_LLM_OPENROUTER_API_KEY` env. var. (required for `openrouter/` models) | — |
| Path to skill file | `--skill` CLI flag | — |
| `critique` stage maximum # of retries | `--critique-max-retries` CLI flag | `2` |
| `ingest` stage maximum # of worker processes | `--ingest-max-workers` CLI flag | `2` |
| `analyse` stage maximum # of concurrent LLM calls | `--analyse-max-workers` CLI flag | `4` |
| MLflow tracking server | `MLFLOW_TRACKING_URI` env. var. | `sqlite:///$HOME/.lasagnastack/mlflow.db` |
| MLflow experiment name | `MLFLOW_EXPERIMENT_NAME` env. var. | `lasagnastack` |

### Architecture

Each stage is a subclass of the `Stage` abstract base class (`base.py`). Adding, removing, or reordering stages requires only editing the `stages` list in `ReelPipeline`. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for four annotated diagrams covering the pipeline data flow, the Stage 4 critique loop, the Stage 6 render + CapCut export, and the extensibility model.

### Get started with Jupyter notebooks

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

### Track LLM costs with MLflow

Every pipeline run is automatically traced with [MLflow](https://mlflow.org). Each LLM API call is recorded as a span (prompt, response, token counts, and latency; Gemini also reports estimated USD cost). Session-level totals are written to the run when the pipeline finishes.

Tracking works out of the box with no setup — runs are written to `~/.lasagnastack/mlflow.db` automatically.

**To browse past runs**, start the MLflow server in a separate terminal:

```bash
mlflow server \
  --backend-store-uri sqlite:///$HOME/.lasagnastack/mlflow.db \
  --host 127.0.0.1 --port 5001
```

> **macOS note:** port 5000 is reserved by AirPlay Receiver. Use 5001 or higher.

Open `http://localhost:5001` in your browser. In **Experiments -> lasagnastack -> Traces**, each run has three span levels: the top-level pipeline span (`ReelPipeline.run`), a per-stage span (e.g. `AnalyseStage.run`), and individual LLM call spans (e.g. `GeminiClient._call_api` or `OpenRouterClient._call_api`) nested inside.

Runs are named `lasagnastack-{brief_stem}-{4-char-id}` and tagged with the model, reel name, and `critique_max_retries`.

**To use a remote MLflow server instead**, set `MLFLOW_TRACKING_URI` as an environment variable:

```
MLFLOW_TRACKING_URI=http://your-mlflow-server:5001
```

Note that runs already stored in `~/.lasagnastack/mlflow.db` will not appear on a remote server — the two stores are independent.

---

## This repo is cool because...

- The pipeline is modularlised into stages, with each stage being responsible for transforming the global state of the pipeline run (similar to LangGraph). It is easy to add, remove, or reorder stages.
- The pipeline supports "skills" -- each user can write their own skill `.md` file to customise the pipeline to their own accounts' styles and branding, or use pre-written skills from marketplaces to cater for different types of reel content.
- Chain-of-thought reasoning is enabled via Gemini's thinking token budget (configurable per stage).
- Human-in-the-loop is deeply integrated in the design, with each stage prompting the user for confirmation before proceeding to the next stage.
- Prompt caching is enabled to avoid unnecessary LLM calls to reduce latency and cost.
- The tool is deeply integrated with its host machine. It auto-detects CapCut Desktop, copies all source media (timeline clips and unused footage) so the project opens in CapCut with no missing-media errors, no manual steps, all your raw clips already in the import panel, and the timeline editor populated and ready to go.
