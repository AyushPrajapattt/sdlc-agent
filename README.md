# Engineering Memory

**Building a source-grounded engineering knowledge graph to help explain why code is the way it is.**

Engineering decisions are scattered across Git history, pull requests, issue trackers, and team discussions. Engineering Memory is designed to preserve those artifacts, normalize them into a common record format, and connect explicitly linked evidence in Neo4j.

> **Current scope:** The ingestion foundation. Evidence retrieval, reasoning, and natural-language "why" answers are future capabilities, not claims of the current implementation.

## The problem

When investigating a codebase, engineers often need to understand more than what a function does. They need to discover which change introduced it, which pull request reviewed it, which issue motivated the work, and which discussion recorded the decision.

Those facts are spread across multiple systems. Engineering Memory aims to make their connections traversable while preserving the source evidence behind each connection.

## Architecture

```mermaid
flowchart TD
    GH["Git history and pull requests"]
    JR["Jira issues"]
    SL["Slack discussions"]

    GH --> A["Source adapters and mappers"]
    JR --> A
    SL --> A

    A --> B["Canonical record contract"]
    B --> C["Deterministic extraction"]
    C --> D["Ingestion runner"]
    D --> E[("Neo4j knowledge graph")]

    E -. "Future capability" .-> F["Evidence retrieval"]
    F -. "Future capability" .-> G["Evidence-backed why answers"]
```

Solid arrows represent the intended ingestion flow. Dotted arrows represent future product capabilities.

## How ingestion works

1. **Read source artifacts.** Adapters handle provider-specific records and pagination.
2. **Normalize records.** Source mappers convert provider payloads into a versioned, source-neutral contract.
3. **Extract explicit facts.** Deterministic extraction preserves identifiers, timestamps, paths, change metadata, source locators, and explicit references.
4. **Persist the graph.** The ingestion runner coordinates bounded processing and Neo4j writes.
5. **Preserve provenance.** Records and relationships retain source information so stored connections can be traced back to their origin.

## Relationship-building principles

- **Stable identity:** canonical IDs are namespaced by provider, workspace, record type, and native ID.
- **Explicit links first:** create source relationships when the source provides an explicit reference.
- **No invented causality:** a shared keyword or nearby timestamp is not proof that one decision caused a code change.
- **Traceable evidence:** retain provenance and source locators where available.
- **Replay safety:** stable IDs and idempotent upserts are intended to prevent duplicate graph entities and relationships.
- **Controlled semantics:** semantic extraction remains disabled by default pending a separately approved policy.

See [Relationship-building system](docs/relationship-building.md) for the detailed relationship rules and requirements gap analysis.

## Project Status and Roadmap

Engineering Memory is being developed in stages. The following separates existing implementation from behavior that still needs verification and capabilities planned for later.

### 1. Built

- Versioned canonical records with source identity and provenance.
- Deterministic extraction of source-grounded values and explicit references.
- GitHub, Jira, and Slack source components.
- An ingestion runner with bounded processing, cursor handling, and run summaries.
- Neo4j persistence code and schema constraints.
- Unit tests: 32 tests passed in the reported run.

### 2. Being Verified

- Real Neo4j integration and graph persistence.
- Idempotent replay against a disposable Neo4j database.
- The complete commit → pull request → issue → discussion evidence chain.
- Relationship direction, stub promotion, and preservation of existing graph links.
- All acceptance criteria in `SPEC.md`.

### 3. Planned

- Retrieve relevant graph paths for natural-language "why" questions.
- Generate answers grounded in source evidence, with traceable citations.
- Represent decision history and detect when later decisions supersede earlier ones.
- Handle missing or conflicting evidence and avoid unsupported answers.
- Consider semantic extraction only after its policy and evidence requirements are approved.

These stages describe the current development picture, not a claim that the entire product is complete. The product specification in `SPEC.md` remains a draft.

## Roadmap

```mermaid
flowchart TD
    A["Source adapters"] --> B["Canonical records"]
    B --> C["Deterministic extraction"]
    C --> D["Neo4j graph ingestion"]
    D --> E["Verify graph and replay"]
    E --> F["Evidence retrieval"]
    F --> G["Why-question answers"]

    style A fill:#dbeafe,stroke:#2563eb,color:#111827
    style B fill:#dbeafe,stroke:#2563eb,color:#111827
    style C fill:#dbeafe,stroke:#2563eb,color:#111827
    style D fill:#dbeafe,stroke:#2563eb,color:#111827
    style E fill:#fef3c7,stroke:#d97706,color:#111827
    style F fill:#ede9fe,stroke:#7c3aed,color:#111827
    style G fill:#ede9fe,stroke:#7c3aed,color:#111827
```

The first four stages represent the ingestion foundation. Graph verification is the next validation milestone; evidence retrieval and "why" answers are future product capabilities.

### Neo4j integration tests

Configure the following environment variables locally:

- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE` (optional)

Then run:

```bash
python -m unittest discover -s tests/integration -v
```

**Important:** Integration tests delete `Artifact` nodes during setup and teardown. Use a disposable test database only, never a production or shared database. Do not commit credentials or secret-bearing environment files.

For fuller instructions, see [`ingestion/TESTING.md`](ingestion/TESTING.md), if present.

## Repository guide

- [`SPEC.md`](SPEC.md) — draft product specification and acceptance criteria
- [`AGENTS.md`](AGENTS.md) — repository workflow instructions
- [`ingestion/`](ingestion/) — ingestion package, adapters, extraction, storage, and tests
- [`docs/relationship-building.md`](docs/relationship-building.md) — relationship model, implemented rules, and gaps against the brief

## Scope boundary

The current ingestion slice builds a provenance-aware graph from explicit source facts. It does not yet establish that a particular discussion caused a code change, infer missing relationships, detect superseded decisions, or generate final answers to "why" questions.

Those capabilities require separate retrieval and reasoning work, clear evidence contracts, and appropriate validation.
