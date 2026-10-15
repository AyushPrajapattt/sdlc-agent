"""Deterministic claim integrity (docs/workbench-api.md, 'Claim semantics'). The model proposes; this code decides.

A cite survives only if its id is retrieved evidence and its quote (if any) is a verbatim substring of that
node's text (whitespace-normalised, case-insensitive). Free text may only contain URLs of retrieved evidence.
"""

from __future__ import annotations

import re

BRACKETED = re.compile(r"[ \t]?\[(https?://[^\]\s]+)\]", re.I)
BARE = re.compile(r"https?://[^\s\]\)>,\"']+", re.I)


def _norm(url: str) -> str:
    """Exact URL identity, except fragment/query noise (the host and path must still match exactly)."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


NOT_ESTABLISHED = {
    "summary": "Not established: the evidence graph contains no records that bear on this question.",
    "claims": [{"text": "The evidence graph holds nothing that answers this question.", "status": "unknown",
                "note": "No evidence was retrieved. Check that the relevant sources are synced and try more "
                        "specific terms (file path, ticket key, PR number).", "cites": []}],
    "gaps": [],
    "confidence": "low",
    "dropped": 0,
}


def strip_urls(text: str, allowed: set[str]) -> tuple[str, set[str]]:
    """Remove URLs that are not evidence URLs. Returns (clean text, removed urls)."""
    removed: set[str] = set()

    def keep_bracket(m):
        if _norm(m.group(1)) in allowed:
            return m.group(0)
        removed.add(m.group(1))
        return ""

    def keep_bare(m):
        url = m.group(0).rstrip(".;:")
        if _norm(url) in allowed:
            return m.group(0)
        removed.add(url)
        return ""

    return BARE.sub(keep_bare, BRACKETED.sub(keep_bracket, text)).strip(), removed


def verify(answer: dict, evidence: dict[str, dict], sufficient: bool, gap: str = "") -> dict:
    """answer = Synthesis dict. Returns {summary, claims[{text,status,note,cites[{node,quote?}]}], gaps, confidence, dropped}."""
    allowed = {_norm(r["url"]) for r in evidence.values() if r.get("url") and not r.get("is_stub")}
    removed: set[str] = set()
    dropped = 0

    def clean(text) -> str:
        out, gone = strip_urls(text or "", allowed)
        removed.update(gone)
        return out

    claims = []
    for c in answer.get("claims") or []:
        status, cites = c["status"], []
        if status != "unknown":  # unknown claims never carry cites
            for ci in c.get("cites") or []:
                row, quote = evidence.get(ci["id"]), (ci.get("quote") or "").strip()
                if row is None or row.get("is_stub") or (quote and _squash(quote) not in _squash(row.get("text") or "")):
                    dropped += 1
                    continue
                cite = {"node": ci["id"], **({"quote": quote} if quote else {})}
                if cite not in cites:
                    cites.append(cite)
        text, note = clean(c.get("text")), clean(c.get("note"))
        if not text:
            continue
        if status == "supported" and not cites:
            status = "inferred"
            note = f"{note} " if note else ""
            note += "Downgraded from supported: no citation could be verified against the retrieved evidence."
        elif status == "inferred" and not note:
            note = "Reasoning beyond what the cited sources state."
        claims.append({"text": text, "status": status, "note": note, "cites": cites})
    if not claims:
        claims.append({"text": "No verifiable claim could be made from the retrieved evidence.", "status": "unknown",
                       "note": "The model returned no usable claims.", "cites": []})

    gaps = [g for g in (clean(g) for g in answer.get("gaps") or []) if g]
    if not sufficient:
        gaps.append("Evidence was judged insufficient" + (f": {gap}" if gap else "."))
    if dropped:
        gaps.append(f"{dropped} citation(s) could not be verified against the retrieved evidence and were removed.")
    if removed:
        gaps.append(f"{len(removed)} URL(s) that are not in the retrieved evidence were removed from the text.")

    supported = any(c["status"] == "supported" for c in claims)
    if dropped or removed or not sufficient or not supported:
        confidence = "low"
    elif gaps or any(c["status"] != "supported" for c in claims):
        confidence = "medium"
    else:
        confidence = "high"
    return {"summary": clean(answer.get("summary")), "claims": claims, "gaps": list(dict.fromkeys(gaps)),
            "confidence": confidence, "dropped": dropped}


def to_legacy(final: dict, evidence: dict[str, dict]) -> dict:
    """Claims -> the old {answer, citations, confidence, uncertainty} shape used by /api/ask."""
    lines, urls, unknown = [final["summary"]], [], []
    for c in final["claims"]:
        if c["status"] == "unknown":
            unknown.append(f"{c['text']} {c['note']}".strip())
            continue
        refs = [evidence[ci["node"]]["url"] for ci in c["cites"] if evidence[ci["node"]].get("url")]
        urls += [u for u in refs if u not in urls]
        tag = "" if c["status"] == "supported" else " (inferred)"
        lines.append(f"- {c['text']}{tag}" + "".join(f" [{u}]" for u in dict.fromkeys(refs)))
    return {"answer": "\n".join(lines), "citations": urls, "confidence": final["confidence"],
            "uncertainty": " ".join([*unknown, *final["gaps"]])}
