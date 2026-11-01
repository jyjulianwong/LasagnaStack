---
hide:
  - navigation
---

<div class="ls-hero" markdown>

![LasagnaStack](lasagna.png){ .ls-hero__logo }

# LasagnaStack

An AI pipeline that turns raw restaurant footage into an editable CapCut
draft for a London foodie Instagram Reel account — seven stages, zero
manual editing.

<div class="ls-hero__actions" markdown>
[Get started](#get-started-with-development){ .md-button .md-button--primary }
[API reference](reference/lasagnastack/){ .md-button }
</div>

[![Tech stack](https://skillicons.dev/icons?i=py,githubactions,apple)](https://skillicons.dev){ .ls-hero__stack }

</div>

<div class="ls-grid ls-grid--bento" markdown>

<div class="ls-card" markdown>
<span class="ls-card__icon">:material-chart-timeline-variant:</span>
### Stage-based pipeline

No agent framework — a shared state object flows through independently
testable stages (ingest, analyse, direct, critique, enhance, render, post
caption), similar in spirit to LangGraph. Adding, removing, or reordering
a stage is a one-line change.
</div>

<div class="ls-card" markdown>
<span class="ls-card__icon">:material-auto-fix:</span>
### Skills

Customise tone and framing per-account with a Markdown skill file, or
generate and iteratively improve one automatically from a folder of
human-edited CapCut drafts via `optimize-skill`.
</div>

<div class="ls-card" markdown>
<span class="ls-card__icon">:material-brain:</span>
### Chain-of-thought reasoning

Per-client control over reasoning token budget, qualitative effort level,
and total output ceiling, supported identically across Gemini and
OpenRouter models.
</div>

<div class="ls-card" markdown>
<span class="ls-card__icon">:material-account-check-outline:</span>
### Human-in-the-loop

Every stage pauses for confirmation before handing off to the next, with
an `--yes` flag to skip prompts once you trust the output.
</div>

<div class="ls-card" markdown>
<span class="ls-card__icon">:material-cached:</span>
### Prompt caching

Gemini responses are cached to disk by content hash, so re-runs after a
tweak never re-bill or re-upload footage that hasn't changed.
</div>

<div class="ls-card" markdown>
<span class="ls-card__icon">:material-movie-open-outline:</span>
### CapCut Desktop, zero setup

Auto-detects CapCut on macOS, copies every clip (timeline and unused
footage) into the draft folder, rewrites media paths, and registers the
project so it's waiting on your home screen when you open the app.
</div>

</div>

<div class="ls-sheet" markdown>

--8<-- "README.md:docs-body"

</div>
