You are annotating an EXISTING plan with the skills each task needs.
DO NOT change goals, files, acceptance, or test commands — just add a
single `Skills:` line per task (under `Files:`).

The plan you must annotate:

{plan}

Available skills (use ONLY these names — never invent new ones):

{catalog}

Rules:
- For each `## TNNN: ...` block, decide which skills the task will need.
  Look at the stack signals: language file extensions, package
  managers, infra tools.
- Output the COMPLETE updated plan, formatted identically to the input
  plus exactly one `Skills:` line per task. Put it right after the
  `Files:` line. Use a comma-separated list of skill names, or `none`
  if no skill applies.
- If a task already has a `Skills:` line, REPLACE it with your fresh
  choice.
- Do NOT wrap the output in code fences. Output raw Markdown.

Example output shape (one task):

## T001: Initialise Python package
Goal: scaffold a package
Files: setup.py, requirements.txt, src/
Skills: python
Acceptance:
- src/ exists
Test command: python setup.py sdist
