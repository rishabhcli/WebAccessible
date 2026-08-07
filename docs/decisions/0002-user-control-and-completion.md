# ADR 0002: User Control and Completion

## Status

Accepted on 2026-08-07.

## Decision

The CDP bridge may open a confirmed routine start URL, observe bounded page state, scroll to a verified target, draw a halo, and verify a user-originated result. It exposes no click, type, fill, submit, tab-close, or Browserbase Agent operation.

Completion is recorded only after a deterministic terminal predicate. A route that reaches a money, identity, or deletion boundary ends as `prepared` until the participant uses the site's real control and a post-action predicate proves completion.
