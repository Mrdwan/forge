You are updating a project's memory bank after completing a development step.

## Completed Step
Step {step_id}: {description}

## Changes Made
{diff_summary}

## Senior Review Summary
{senior_review}

## Current Memory Files

### ROADMAP.md (current)
{current_roadmap}

### ARCHITECTURE.md (current)
{current_arch}

### DECISIONS.md (current)
{current_decisions}

## Instructions

Output exactly three sections, separated by "===SECTION===" markers:

1. ROADMAP.md — Check off the completed step (change `- [ ]` to `- [x]`). Immediately below the checked step, add a new line starting with `> ` containing a very brief summary of what changed (e.g., `> Moved to src/ layout, added hooks`). Keep all other steps unchanged.

2. ARCHITECTURE.md — Update ONLY if the system structure changed (new components, new data flows, schema changes). If no structural changes, output the existing content unchanged. Do NOT add information about implementation details that don't affect architecture.

3. DECISIONS.md — Add an entry ONLY if a significant design decision was made during this step (e.g., chose a specific pattern, rejected an approach). If no new decisions, output existing content unchanged.

Keep all files concise. Under 50 lines each. Remove outdated information.

Format:
===ROADMAP===
[updated roadmap content]
===ARCHITECTURE===
[updated architecture content]
===DECISIONS===
[updated decisions content]
