"""Versioned, structured prompts for the investigation agent.

Bump PROMPT_VERSION whenever any prompt or schema changes; it is stamped on every answer.
"""

from typing import Literal

from pydantic import BaseModel, Field

from .harness import DESCRIPTIONS, GRAPH_MODEL

MODES = ("why", "debug", "change")

TOOLS_TEXT = "\n".join(f"- {d}" for d in DESCRIPTIONS.values())
MODE_TASK = {
    "why": "The user asks why code, a setting or a behaviour is the way it is. Find the decision, its reason and who/what drove it.",
    "debug": "The user pasted an error, stack trace or log. Find the history of the files and keys involved: recent changes, "
             "incidents and decisions that could explain the failure. Do not guess a root cause the evidence does not state.",
    "change": "The user asks whether it is safe to change something. List the constraints, decisions and incidents that guard "
              "this code and what would break or regress if it changed, each with its source.",
}


class Understanding(BaseModel):
    intent: str = Field(description="One sentence: what the user actually wants to know.")
    entities: list[str] = Field(description="File paths, ticket keys, PR numbers, people, or terms named in the question.")
    time_hint: str | None = Field(description="Any time window mentioned, else null.")


UNDERSTAND = """You analyse questions about engineering history.
{graph_model}

Task: {task}

Input: {question}

Extract the intent, the concrete entities worth searching for, and any time window."""


class ToolCall(BaseModel):
    tool: Literal["find_text", "file_history", "neighbors", "evidence_chain", "get", "cypher_query"]
    arg: str = Field(description="Query words, file path fragment, a canonical id already seen in evidence, "
                                 "or (cypher_query) a plain-language question.")


class Plan(BaseModel):
    reasoning: str = Field(description="Short note on what is missing and why these calls fill it.")
    calls: list[ToolCall] = Field(description="1-5 retrieval calls. Never repeat a call already made.")


PLAN = """You plan graph retrieval to answer an engineering-history question. You cannot write queries; you choose tools.

{graph_model}

Tools:
{tools}

Task: {task}
Intent: {intent}
Entities: {entities}
Attempt: {attempt} of {max_attempts}
Calls already made (never repeat any): {done_calls}
Calls refused: {rejected}
Evidence gathered so far:
{evidence}
Gap reported by the last sufficiency check: {gap}

Choose the next 1-5 calls. Without a foothold use find_text / file_history. Once evidence exists, prefer
evidence_chain or neighbors on the most promising ids to follow commit -> PR -> issue -> discussion links.
Ids for neighbors/evidence_chain/get must be copied exactly from the evidence above.
Prefer the fixed tools. Use cypher_query only for multi-hop, aggregate or filter questions they cannot express."""

PROMPT_VERSION = "v3"


class CypherOut(BaseModel):
    cypher: str = Field(description="ONE read-only Cypher statement, no parameters.")


CYPHER_GEN = """Write ONE read-only Cypher query for this question about an engineering-history graph.

{card}

Question: {question}
{error}"""


class Sufficiency(BaseModel):
    sufficient: bool = Field(description="True only if the evidence directly supports an answer.")
    relevant_ids: list[str] = Field(description="canonical_ids of evidence that actually bears on the question.")
    gap: str = Field(description="What is still missing, or empty if sufficient.")


SUFFICIENCY = """Judge whether this evidence is enough to answer the question with citations.

Task: {task}
Input: {question}
Evidence:
{evidence}

Be strict: correlation in time is not a stated reason. Name the gap precisely if insufficient."""


class Answer(BaseModel):
    answer: str = Field(description="Direct answer. Every claim cites a source URL in [brackets].")
    citations: list[str] = Field(description="Source URLs used.")
    confidence: Literal["high", "medium", "low"]
    uncertainty: str = Field(description="What the evidence does not establish. Empty only if nothing.")


SYNTHESIZE = """Answer using ONLY the evidence below.

Task: {task}
Rules:
- Cite each claim inline as [url] using the exact url of an evidence item; list the same urls in citations.
- State what the evidence does not establish in uncertainty. If something is not in the evidence write "not established" instead of guessing.
- Edges are explicit links only. Two things happening at similar times is not a reason or a cause.
- If the attempt limit was hit or evidence is thin, say so and lower confidence.

Input: {question}
Evidence sufficient: {sufficient}
Evidence:
{evidence}"""
