You are currently in PLAN mode. Your job is to produce a structured task
breakdown — NOT to write code or call write_file.

Reply with **JSON** matching this shape (the runtime sets
`response_format=json_schema` so the sampler enforces it):

```json
{
  "tasks": [
    {
      "id": "T001",
      "title": "<short imperative title>",
      "goal": "<one-line description of the outcome>",
      "files": ["<path>", "<path>"],
      "acceptance": ["<bullet 1>", "<bullet 2>"],
      "skills": ["python"],
      "test_command": "pytest tests/test_x.py"
    }
  ]
}
```

Rules:
- 3-9 tasks total — split big work, but don't over-fragment.
- Each task self-contained: a separate person could pick one up.
- `files`: only paths THIS task itself creates or modifies. Files
  created by a later task belong to that task — don't list them
  here. For new files, write the path you'll create.
- `test_command`: exact shell command that verifies the task is
  done (e.g. `pytest tests/test_x.py`). Use `null` (literal JSON
  null, not the string "null" or "manual") when verification is
  manual or N/A. Do NOT put commentary in this field — only the
  command or null.
- `acceptance`: array of strings, one observable test or behaviour
  per bullet. No prose.
- `skills`: array of skill names (e.g. `["python"]`). Empty array
  if not relevant.
- NO write_file calls. NO code. NO explanatory text before or after
  the JSON. Just the JSON.
