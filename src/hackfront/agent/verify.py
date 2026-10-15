"""Deterministic answer integrity: only URLs of retrieved evidence may be cited."""

from __future__ import annotations

import re

BRACKETED = re.compile(r"[ \t]?\[(https?://[^\]\s]+)\]")
BARE = re.compile(r"https?://[^\s\]\)>,\"']+")

NOT_ESTABLISHED = {
    "answer": "Not established: the evidence graph contains no records that bear on this question.",
    "citations": [],
    "confidence": "low",
    "uncertainty": "No evidence was retrieved, so nothing can be stated. Check that the relevant sources are synced "
                   "and try more specific terms (file path, ticket key, PR number).",
}


def verify(answer: dict, evidence: dict[str, dict], sufficient: bool, gap: str = "") -> dict:
    """Drop unsupported URLs from text and citations, add an uncertainty note, cap confidence."""
    allowed = {r["url"] for r in evidence.values() if r.get("url") and not r.get("is_stub")}
    removed: set[str] = set()

    def keep_bracket(m):
        if m.group(1) in allowed:
            return m.group(0)
        removed.add(m.group(1))
        return ""

    def keep_bare(m):
        url = m.group(0).rstrip(".;:")
        if url in allowed:
            return m.group(0)
        removed.add(url)
        return ""

    text = BARE.sub(keep_bare, BRACKETED.sub(keep_bracket, answer["answer"]))
    inline = [u for u in BRACKETED.findall(text)]
    citations = []
    for url in [*answer.get("citations", []), *inline]:
        if url in allowed:
            if url not in citations:
                citations.append(url)
        else:
            removed.add(url)

    confidence = answer["confidence"]
    notes = [answer.get("uncertainty", "").strip()]
    if removed:
        notes.append(f"{len(removed)} unsupported citation(s) were removed because they are not in the retrieved evidence.")
        confidence = "low"
    if not sufficient:
        notes.append("The evidence was judged insufficient" + (f": {gap}" if gap else "."))
        confidence = "low"
    if not citations:
        notes.append("No supported citation remains for this answer.")
        confidence = "low"
    return {"answer": text.strip(), "citations": citations,
            "confidence": confidence,
            "uncertainty": " ".join(n for n in notes if n)}
