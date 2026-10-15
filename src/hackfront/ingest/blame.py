"""Per-line blame for ONE path by replaying commit patches (oldest -> newest).

Pure: no I/O. Input is [(commit_id, unified_diff_patch | None)]; output is
{"lines": [{"text", "blame"}], "complete": bool, "note"?: str}.

A line is only ever reported when the whole history needed to know it was replayed cleanly. Any gap (missing
patch, history that does not start at file creation, a patch that does not apply) returns complete=False,
NO lines, and a note saying why: partial text would be a guess. Renames are not followed.
# ponytail: renames/copies are not tracked; follow `previous_filename` here if rename history matters.
"""

from __future__ import annotations

import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(ValueError):
    pass


def _parse_hunks(patch: str) -> list[tuple[int, int, int, int, list[str]]]:
    """-> [(old_start, old_count, new_start, new_count, body_lines)], bodies cut by the header counts."""
    rows = patch.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    hunks, i = [], 0
    while i < len(rows):
        m = _HUNK.match(rows[i])
        if not m:
            raise PatchError(f"unexpected line outside a hunk: {rows[i][:40]!r}")
        a, b, c, d = int(m[1]), int(1 if m[2] is None else m[2]), int(m[3]), int(1 if m[4] is None else m[4])
        i += 1
        body, old, new = [], 0, 0
        while old < b or new < d:
            if i >= len(rows):
                raise PatchError("hunk is shorter than its header says")
            row = rows[i]
            tag = row[:1] or " "  # some tools strip the single space off blank context lines
            if tag == " ":
                old, new = old + 1, new + 1
            elif tag == "-":
                old += 1
            elif tag == "+":
                new += 1
            else:
                raise PatchError(f"bad hunk line: {row[:40]!r}")
            body.append(row if row else " ")
            i += 1
        if old != b or new != d:
            raise PatchError("hunk body does not match its header counts")
        while i < len(rows) and rows[i].startswith("\\"):  # "\ No newline at end of file"
            i += 1
        hunks.append((a, b, c, d, body))
    if not hunks:
        raise PatchError("patch has no hunks")
    return hunks


def apply_patch(lines: list[tuple[str, str]], patch: str, commit_id: str) -> list[tuple[str, str]]:
    """Apply one patch to [(text, blame)]; '+' lines are attributed to commit_id. Raises PatchError on mismatch."""
    out: list[tuple[str, str]] = []
    pos = 0  # next unconsumed index in `lines`
    for a, b, _c, _d, body in _parse_hunks(patch):
        start = a if b == 0 else a - 1  # a zero-length old range means "insert after line a"
        if start < pos or start > len(lines):
            raise PatchError(f"hunk @@ -{a},{b} is out of order or beyond the end of the file")
        out += lines[pos:start]
        pos = start
        for row in body:
            tag, text = row[0], row[1:]
            if tag == "+":
                out.append((text, commit_id))
                continue
            if pos >= len(lines) or lines[pos][0] != text:
                raise PatchError(f"line {pos + 1} does not match the patch ({'context' if tag == ' ' else 'removed'} line)")
            if tag == " ":
                out.append(lines[pos])
            pos += 1
    return out + lines[pos:]


def _short(commit_id: str) -> str:
    return commit_id.rsplit(":", 1)[-1][:7]


def blame(patches: list[tuple[str, str | None]]) -> dict:
    """Replay `patches` (oldest -> newest) for one path."""

    def fail(note: str) -> dict:
        return {"lines": [], "complete": False, "note": note}

    if not patches:
        return fail("No commits touching this path were ingested.")
    lines: list[tuple[str, str]] = []
    note = None
    for index, (commit_id, patch) in enumerate(patches):
        if not patch:
            return fail(f"Commit {_short(commit_id)} has no patch for this file (binary, too large, empty or a pure "
                        "rename; renames are not followed), so its content is unknown.")
        try:
            hunks = _parse_hunks(patch)
            if index == 0 and (hunks[0][0], hunks[0][1]) != (0, 0):
                return fail(f"History starts at commit {_short(commit_id)}, which modifies the file instead of "
                            "creating it: earlier history was not ingested.")
            lines = apply_patch(lines if index else [], patch, commit_id)
        except PatchError as error:
            return fail(f"Commit {_short(commit_id)} does not apply to the replayed history: {error}.")
        if not lines:
            note = f"File is empty or deleted as of commit {_short(commit_id)}."
    if note and not lines:
        return fail(note)
    return {"lines": [{"text": t, "blame": b} for t, b in lines], "complete": True}
