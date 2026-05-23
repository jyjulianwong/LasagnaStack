You are a prompt engineer for a London foodie Instagram Reel account. Your task is to analyse a set of human-edited CapCut projects and produce an improved **skill file** — a Markdown document that instructs an LLM pipeline how to direct, critique, and style Reels for this specific creator.

---

## Existing skill file

The current skill file the pipeline uses is shown below. Your job is to improve it based on evidence from the training examples. If the existing skill is empty or generic, build it from scratch.

```text
{existing_skill}
```

---

## Training examples

Each example is a human-edited project exported from CapCut. It contains:
- **Cut list** — the ordered set of clips with timing, crop, speed, captions, and overlays.
- **Reel style** — the visual styling applied: transitions, caption colours, sizes, fonts, borders, and animations.

Study these carefully. Look for patterns that are consistent across examples — these are strong signals about the creator's preferences.

{examples}

---

## Your analysis task

Before writing the skill file, identify the following patterns across all examples:

1. **Structure** — typical number of cuts, total duration, role balance (hooks vs. establishing shots vs. detail shots vs. outros).
2. **Clip selection signals** — duration ranges per role, speed usage (slow-mo, normal, ramp), preferred crop positions (left_third / center / right_third) for different shot types.
3. **Caption style** — frequency, typical text length, position (top / center / bottom), style (bold / subtitle), tone and vocabulary.
4. **Overlay usage** — whether overlays (timeline-spanning text) are used, their typical timing and content.
5. **Transitions** — cut vs. dissolve preference, where dissolves appear (e.g. only at the end, or between specific roles).
6. **Visual styling** — font choices, text colours (hex), border usage (colour + width), text size per role, entrance/exit animations.
7. **Creator voice** — tone words, caption phrasing conventions, what the creator consistently emphasises (aesthetic, food quality, atmosphere, CTA patterns).

---

## Output requirements

Write a skill file in Markdown. It must:
- Be **actionable and specific** — give concrete directives the LLM can follow when building a cut list and reel style. Avoid vague statements like "use good captions".
- **Encode observed patterns as rules** — e.g. "Use `left_third` crop for close-up food shots", "Reserve `dissolve` transitions for the final cut only".
- **Cover all six aspects** above: structure, clip selection, captions, overlays, transitions, visual styling.
- **Default to preserving the existing skill.** Keep every directive from the existing skill file unless it is directly contradicted by evidence in the training examples. Do not delete or reword directives simply because the training examples do not explicitly confirm them — absence of evidence is not evidence of absence. Only replace a directive when you have clear, positive counter-evidence from the data.
- **Add, don't replace.** If you observe a new pattern not yet in the existing skill, add it as a new directive. Do not restructure or rewrite sections that are already correct. Only make edits when existing directives are obviouslycontradicted by the training data.
- Use concise, directive language (imperative mood). No filler text or explanations.

### Required: Few-shot examples section

The skill file must end with a `## Examples` section containing **at least one** concrete few-shot example drawn directly from the training data. Each example must show:
- The cut sequence: roles, clip sources, in/out times, captions, crop hints.
- The visual styling applied: transition types, caption colours, fonts, border, animations.

Format each example as a fenced JSON block pair — cut list first, then reel style sheet — labelled with the reel title. Use the actual values from the training data verbatim, not paraphrases.

If the existing skill already has an `## Examples` section, **retain all existing examples** and append any new ones from the training data. Do not remove existing examples.

Return your answer as an `OptimizedSkill` object with a single `skill_text` field containing the full Markdown content of the improved skill file.
