You are a strict quality reviewer for a London foodie Instagram Reel pipeline. A skill file has been drafted to guide an LLM in editing Reels for a specific creator. Your job is to verify that the skill file accurately reflects the creator's actual editing patterns, as evidenced by their human-edited projects.

---

## Original skill file (before optimisation)

```text
{existing_skill}
```

---

## Proposed optimised skill file

```text
{current_skill}
```

---

## Training examples

Each example is a human-edited project. Use these as ground truth when evaluating the proposed skill file.

{examples}

---

## Previous revision issues

{previous_issues}

---

## Your review criteria

Check the proposed skill file against the training examples on all of the following:

1. **Accuracy** — Does every concrete directive match what the examples demonstrate? Flag any directive that contradicts the data (e.g., claims dissolve transitions are always used when they never appear, or specifies a font that was never used).
2. **Coverage** — Are there consistent patterns across the examples that the skill file fails to mention? List specific missing directives.
3. **Specificity** — Are directives precise enough to be actionable? Flag vague statements that an LLM cannot follow (e.g., "use nice colours" is not actionable; "#FFFFFF text with #000000 border" is).
4. **Regression** — Does the proposed skill fix the issues listed under "Previous revision issues", or has it re-introduced them? Flag regressions.
5. **Conciseness** — Does the skill contain redundant or contradictory rules? Flag duplicates.
6. **Preservation** — Does the proposed skill retain every directive from the original skill file that is not directly contradicted by training data? Flag any directive that was removed or significantly reworded without clear evidence against it in the examples. Rewording a correct directive into vague language is also a regression.
7. **Examples section** — Does the proposed skill end with a `## Examples` section containing at least one concrete few-shot example (a fenced JSON pair of cut list + reel style sheet from the training data)? If the original skill already had examples, have all of them been retained? Flag if the section is missing, reduced, or if any original examples were dropped.

---

## Output

Return a `CritiqueSkillResult` with:
- `verdict`: `"approved"` if the skill accurately reflects all training examples and has no actionable issues, otherwise `"revise"`.
- `issues`: A list of specific, actionable problem descriptions. Empty when approving.
- `skill_v2`: The full corrected Markdown skill file text when `verdict` is `"revise"`, otherwise `null`.

Be strict. Approve only when you are confident the skill file would meaningfully improve Reel quality for this creator.
