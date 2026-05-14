"""LM Studio runtime status — knowing if the model is busy or idle.

The LM Studio REST API doesn't expose runtime processing state.
`/api/v1/models` shows whether a model is loaded but not whether
it's currently generating. The WebSocket SDK has a private
`getInstanceProcessingState` endpoint that `lms ps` uses to show
STATUS=GENERATING/LOADED — we shell out to that CLI here because
SDK Python doesn't expose this state.

Why this matters: probe-suite v2 sessions fire many sequential
LLM calls. If the previous call is still in flight (the model is
GENERATING), a new POST /v1/chat/completions queues behind it for
minutes. Callers can't distinguish "model stuck" from "model
busy" without `lms ps`. This module gives an explicit answer.

If `lms` is not on PATH (production users without LM Studio CLI),
all probes return `None` — caller treats this as "unknown, assume
free" and continues as before.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

LMS_BINARY_CANDIDATES = (
    "lms",
    "/home/adegtyarev/.lmstudio/bin/lms",  # default install path
)

Status = Literal["LOADED", "IDLE", "GENERATING", "LOADING", "UNKNOWN"]


@dataclass(frozen=True)
class InstanceStatus:
    """One row of `lms ps` output. `status` is the runtime state we
    care about; the rest is reference info for diagnostics."""

    identifier: str
    model: str
    status: Status
    size: str
    context: str
    parallel: str
    device: str
    ttl: str


def _find_lms_binary() -> str | None:
    """Return path to `lms` CLI or None if missing."""
    for candidate in LMS_BINARY_CANDIDATES:
        if shutil.which(candidate) is not None:
            return candidate
        # shutil.which doesn't handle full paths the same way
        from pathlib import Path

        if Path(candidate).is_file():
            return candidate
    return None


def _parse_lms_ps(output: str) -> list[InstanceStatus]:
    """Parse the table format `lms ps` emits. Header line has the
    column names; rows below are whitespace-delimited.

    Format observed 2026-05-14 (lms CLI bundled with LM Studio 0.4):

        IDENTIFIER  MODEL  STATUS  SIZE  CONTEXT  PARALLEL  DEVICE  TTL
        qwen/qwen2.5-coder-14b  qwen/qwen2.5-coder-14b  GENERATING  8.99 GB  16384  1  Local

    Multi-word fields (SIZE = `8.99 GB`) make naive split() wrong.
    We split on multiple spaces (≥2) which the table uses for column
    separation."""
    import re

    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    # Find header row — it has IDENTIFIER as first column. Below it
    # are data rows. lms ps may print warnings/info above the table,
    # so we look for the header explicitly.
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("IDENTIFIER"):
            header_idx = i
            break
    if header_idx is None:
        return []
    rows = []
    for line in lines[header_idx + 1 :]:
        # Split on 2+ spaces — the table uses padding.
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 7:
            continue
        # Some columns can be empty / blank; pad to 8 expected fields.
        while len(parts) < 8:
            parts.append("")
        identifier, model, status_str, size, context, parallel, device, ttl = parts[:8]
        status: Status
        # Observed statuses, 2026-05-14: LOADED, IDLE (after unload+load),
        # GENERATING (in progress), LOADING. IDLE and LOADED both mean
        # "ready, not busy" — UI vocabulary varies by lifecycle.
        if status_str == "GENERATING":
            status = "GENERATING"
        elif status_str == "LOADED":
            status = "LOADED"
        elif status_str == "IDLE":
            status = "IDLE"
        elif status_str == "LOADING":
            status = "LOADING"
        else:
            status = "UNKNOWN"
        rows.append(
            InstanceStatus(
                identifier=identifier,
                model=model,
                status=status,
                size=size,
                context=context,
                parallel=parallel,
                device=device,
                ttl=ttl,
            )
        )
    return rows


def list_loaded(timeout: float = 5.0) -> list[InstanceStatus] | None:
    """Return all loaded LLM instances with their runtime status, or
    None if `lms` CLI is unavailable. Callers without `lms` get None
    and should treat that as "status unknown, proceed".

    Why `lms` not REST: `/api/v1/models` shows `loaded_instances` but
    doesn't expose whether they're generating. The WS endpoint
    `getInstanceProcessingState` is private; `lms ps` is the
    cleanest publicly-callable wrapper today."""
    binary = _find_lms_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, "ps"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return _parse_lms_ps(result.stdout)


def cancel_generation(model_id: str, timeout: float = 10.0) -> bool | None:
    """Hard-stop the model by unloading it. Returns True on success,
    False on failure, None if `lms` CLI is missing.

    This is the **blunt** cancellation path: `lms unload` kills the
    in-flight inference and clears the model from memory. Next chat
    completion will trigger an auto-reload (~5s warm-up on a 14B
    Q4_K_M / 8.99 GB). We lose the warm KV cache and pay the load
    time.

    Used for: user pressed Esc to abort a /go that's stuck, probe
    runner cleanup between scenarios, hung-inference recovery.
    Not used for: routine completion of one chat — for that, just
    close the streaming connection on the client.

    A cleaner cancellation (via WS-SDK cancellation token, without
    losing the model) is an open task — see [[reference_lmstudio_status]]
    memory for status."""
    binary = _find_lms_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, "unload", model_id],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def is_busy(model_id: str | None = None, timeout: float = 5.0) -> bool | None:
    """Return True if any loaded model (or the named one) is in
    STATUS=GENERATING, False if it's idle (LOADED), None if unknown
    (lms CLI missing, parse failed, etc.).

    `None` is deliberate — callers should distinguish "definitely
    busy" from "can't tell" and not block on the latter."""
    instances = list_loaded(timeout=timeout)
    if instances is None:
        return None
    if model_id is not None:
        instances = [i for i in instances if i.identifier == model_id]
    if not instances:
        return False
    return any(i.status == "GENERATING" for i in instances)


__all__ = ["InstanceStatus", "Status", "cancel_generation", "is_busy", "list_loaded"]
