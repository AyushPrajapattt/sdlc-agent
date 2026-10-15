import json

import pytest

from hackfront.ingest.contracts import (
    Artifact, Change, Provenance, RecordKind, RelationshipKind as R, SourceIdentity, SourceReference,
)
from hackfront.ingest.storage.neo4j import Neo4jStore

K = RecordKind


def ident(rtype, sid):
    return SourceIdentity("github", "acme", rtype, sid, f"https://example.test/{rtype}/{sid}")


def art(rtype, sid, kind, title, text, time, paths=(), refs=()):
    return Artifact(
        source=ident(rtype, sid), kind=kind, observed_at="2024-06-01T00:00:00Z", event_time=time,
        title=title, text=text, raw_payload={}, change=Change(paths=tuple(paths)) if paths else None,
        provenance=Provenance(f"https://example.test/{rtype}/{sid}", "$", "2024-06-01T00:00:00Z", "t/1"),
        references=tuple(SourceReference(ident(t, i), rel, loc) for t, i, rel, loc in refs),
    )


def cid(rtype, sid):
    return ident(rtype, sid).canonical_id


def url(rtype, sid):
    return f"https://example.test/{rtype}/{sid}"


class Scripted:
    """Fake OpenAI client: answers by the schema title found in the prompt. `answer` is the Synthesis payload."""

    def __init__(self, plan_calls, answer=None, sufficient=True, relevant=None):
        self.plan_calls, self.answer, self.sufficient, self.seen = plan_calls, answer, sufficient, []
        self.prompts = []
        self.relevant = relevant if relevant is not None else [cid("pull_request", "pr1"), cid("issue", "issue1")]
        self.chat = self
        self.completions = self

    def create(self, model, messages, max_tokens):
        title = json.loads(messages[0]["content"].split("matching this JSON Schema:\n")[-1])["title"]
        self.seen.append(title)
        self.prompts.append(messages[0]["content"])
        out = {
            "Understanding": {"intent": "why cap", "entities": ["PAY-412"], "time_hint": None},
            "Plan": {"reasoning": "start", "calls": self.plan_calls},
            "Sufficiency": {"sufficient": self.sufficient, "relevant_ids": self.relevant,
                            "gap": "" if self.sufficient else "no design doc"},
            "Synthesis": self.answer,
            "CypherOut": {"cypher": "MATCH (i:Artifact {record_kind:'issue'}) RETURN i"},
        }[title]
        msg = type("M", (), {"content": json.dumps(out)})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


@pytest.fixture
def fake(monkeypatch):
    from hackfront.agent import llm

    def install(f):
        monkeypatch.setattr(llm, "_clients", {"azure": f})
        return f
    return install


@pytest.fixture
def graph(clean_graph):
    """c2 <-parent- c1 <-CONTAINS- pr1 -> issue1, pr1 -> thread1 <-REPLIES_TO- msg1, pr1 -> stubx <- issue2."""
    store = Neo4jStore(clean_graph)
    for a in (
        art("commit", "c2", K.GIT_COMMIT, "initial gateway", "first version", "2024-01-01T00:00:00Z", ["src/pay/gateway.py"]),
        art("commit", "c1", K.GIT_COMMIT, "cap gateway retries", "limit retries to 3 PAY-412", "2024-02-01T00:00:00Z",
            ["src/pay/gateway.py", "src/pay/retry.py"], [("commit", "c0", R.REFERENCES, "$.parents[1]"),
                                                         ("commit", "c2", R.REFERENCES, "$.parents[0]")]),
        art("pull_request", "pr1", K.PULL_REQUEST, "Cap retries", "Fixes PAY-412 retry storm. " + "x" * 700, "2024-02-02T00:00:00Z",
            refs=[("commit", "c1", R.CONTAINS, "$.commits[0]"), ("issue", "issue1", R.REFERENCES, "$.body"),
                  ("thread", "thread1", R.REFERENCES, "$.body"), ("misc", "stubx", R.REFERENCES, "$.body")]),
        art("issue", "issue1", K.ISSUE, "PAY-412 retries overload gateway", "gateway retries caused the outage", "2024-01-30T00:00:00Z"),
        art("issue", "issue2", K.ISSUE, "Unrelated billing", "invoice rounding", "2024-01-31T00:00:00Z",
            refs=[("misc", "stubx", R.REFERENCES, "$.body")]),
        art("thread", "thread1", K.DISCUSSION_THREAD, "ops thread", "we decided to cap gateway retries at 3", "2024-01-31T12:00:00Z"),
        art("message", "msg1", K.DISCUSSION_MESSAGE, None, "agreed, three is enough", "2024-01-31T13:00:00Z",
            refs=[("thread", "thread1", R.REPLIES_TO, "$.thread_ts")]),
    ):
        store.write_artifact(a)
    return clean_graph
