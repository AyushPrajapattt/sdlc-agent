"""Versioned, structured prompts for the investigation agent.

Bump PROMPT_VERSION whenever any prompt or schema changes; it is stamped on every answer.
"""

from typing import Literal

from pydantic import BaseModel, Field

PROMPT_VERSION = "v1"


# --- 2. Question understanding -------------------------------------------------

class Understanding(BaseModel):
    intent: str = Field(description="One sentence: what the user actually wants to know.")
    entities: list[str] = Field(description="File paths, ticket keys, PR numbers, people, or terms named in the question.")
    time_hint: str | None = Field(description="Any time window mentioned, else null.")


UNDERSTAND = """You analyse questions about why code is the way it is.
The evidence store is a graph of commits, pull requests, issues, and discussion threads/messages.

Question: {question}

Extract the intent, the concrete entities worth searching for, and any time window."""


# --- 3. Investigation planning ---------------------------------------------------

class ToolCall(BaseModel):
    tool: Literal["search_text", "search_path", "expand"] = Field(
        description="search_text: keyword in titles/bodies. search_path: changed file path fragment. "
                    "expand: neighbours of a known canonical_id."
    )
    arg: str = Field(description="Keyword, path fragment, or canonical_id.")


class Plan(BaseModel):
    reasoning: str = Field(description="Short note on what is missing and why these calls fill it.")
    calls: list[ToolCall] = Field(description="1-5 retrieval calls. Never repeat a call already made.")


PLAN = """You plan graph retrieval to answer an engineering-history question.

Intent: {intent}
Entities: {entities}
Attempt: {attempt} of {max_attempts}
Calls already made: {done_calls}
Evidence gathered so far:
{evidence}
Gap reported by the last sufficiency check: {gap}

Choose the next 1-5 retrieval calls. Prefer `expand` on promising evidence ids to follow
commit -> PR -> issue -> discussion links once you have a foothold."""


# --- 7. Sufficiency check ----------------------------------------------------------

class Sufficiency(BaseModel):
    sufficient: bool = Field(description="True only if the evidence directly supports an answer.")
    relevant_ids: list[str] = Field(description="canonical_ids of evidence that actually bears on the question.")
    gap: str = Field(description="What is still missing, or empty if sufficient.")


SUFFICIENCY = """Judge whether this evidence is enough to answer the question with citations.

Question: {question}
Evidence:
{evidence}

Be strict: correlation in time is not a stated reason. Name the gap precisely if insufficient."""


# --- 9. Answer synthesis ---------------------------------------------------------------

class Answer(BaseModel):
    answer: str = Field(description="Direct answer. Every claim cites a source URL in [brackets].")
    citations: list[str] = Field(description="Source URLs used.")
    confidence: Literal["high", "medium", "low"]
    uncertainty: str = Field(description="What the evidence does not establish. Empty only if nothing.")


SYNTHESIZE = """Answer the question using ONLY the evidence below. Cite source URLs inline.
If evidence is thin or the attempt limit was hit, say what is unknown instead of guessing.

Question: {question}
Evidence sufficient: {sufficient}
Evidence:
{evidence}"""
