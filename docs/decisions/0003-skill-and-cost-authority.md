# ADR 0003: Skill and Cost Authority

## Status

Accepted on 2026-08-07.

## Decision

EverOS `agent_skill` content uses validated YAML front matter plus readable Markdown. Each verified edit or repair creates a new immutable revision. Replay resolves selectors in ARIA/name, visible-text, then CSS order and calls no model on a matching verified step.

Snowflake product-owned rows are the only displayed cost authority. Model calls retain actual provider token usage and effective rate-card lineage. `ACCOUNT_USAGE` is never queried for the live cost curve.
