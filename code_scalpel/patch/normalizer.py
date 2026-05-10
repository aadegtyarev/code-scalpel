from __future__ import annotations

import re

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)")


def fix_hunk_headers(patch: str) -> str:
    """Recount actual lines in each hunk and rewrite @@ headers.

    LLMs often produce wrong line counts in hunk headers (most commonly
    forgetting blank context lines). git apply rejects these strictly.
    This function makes the headers match the actual diff content so that
    git apply accepts the patch.
    """
    lines = patch.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _HUNK_HEADER.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue

        old_start = int(m.group(1))
        new_start = int(m.group(2))
        rest = m.group(3)  # trailing comment after @@

        # Collect hunk body until next @@ or end
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith("@@"):
            body.append(lines[j])
            j += 1

        old_count = sum(1 for ln in body if ln.startswith("-") or ln.startswith(" "))
        new_count = sum(1 for ln in body if ln.startswith("+") or ln.startswith(" "))

        def _fmt(start: int, count: int) -> str:
            return f"{start}" if count == 1 else f"{start},{count}"

        header = f"@@ -{_fmt(old_start, old_count)} +{_fmt(new_start, new_count)} @@{rest}"
        out.append(header if header.endswith("\n") else header + "\n")
        out.extend(body)
        i = j

    return "".join(out)
