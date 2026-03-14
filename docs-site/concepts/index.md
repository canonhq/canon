# Concepts

Canon is built on a few core ideas that distinguish it from traditional documentation tools. Understanding these concepts will help you get the most out of the platform.

## Core Thesis

Documentation fails because it's a **write-once artifact**. Canon treats docs as **living programs** — all markdown is input, AI agents are the runtime, code is the ground truth, and the repo is the execution environment.

Specs define **intent** — what should be built. Code reveals **reality** — what actually shipped. Other docs (ADRs, guides, READMEs) provide **context** — why decisions were made. The platform closes the loop across all three, continuously evaluating whether intent matches reality and keeping context accurate.

## Key Concepts

### [Spec-Driven Development](./spec-driven-development)

The structured artifact model that makes specs machine-readable. Proposals, sections, acceptance criteria, and tasks — all in markdown, all tracked.

### [Living Specs](./living-specs)

The feedback loop that keeps documentation alive. PMs write specs, agents create tickets, engineers write code, agents verify implementation, docs auto-update.

### [Delta Tracking](./delta-tracking)

How Canon tracks changes through status transitions and hidden comments rather than rewriting specs.

### [Agent Mesh](./agent-mesh)

The agent architecture — from single-repo agents to cross-repo coordination to the org-wide knowledge brain.

### [Spec Coverage](./coverage)

The metric model that measures what percentage of spec acceptance criteria are verified against actual code.
