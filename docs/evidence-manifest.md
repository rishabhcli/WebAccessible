# Evidence Manifest

No end-to-end cold or warm qualification run has been frozen yet.

## Browserbase provider qualification - 2026-08-07

This is sanitized provider-only evidence, not a participant task-run claim.

| Evidence | Result |
|---|---|
| Session reference | SHA-256 prefix `e05ede2a19f4`; raw ID omitted |
| Target | Exact configured W3C sandwich checkbox example |
| Create and CDP attach | Completed in 4.49 seconds |
| Live View | HTTPS URL returned; raw URL omitted |
| Observation snapshot | 49 visible candidates in 70 ms: 44 links, 4 checkboxes, 1 without an explicit role; 0 sensitive candidates |
| Action boundary | No Browserbase Agent, click, typing, fill, submit, or other target-page action |
| Termination | Controller stop completed in 153 ms; provider state `COMPLETED`; end timestamp present |
| Independent readback | Latest metadata-marked session was `COMPLETED` and recorded `agentSurfaceUsed=false` |

The live metadata endpoint required string-valued metadata, so the integration records `agentSurfaceUsed` as the truthful string `"false"`. Startup reconciliation queries only nonterminal sessions and terminates only entries carrying the current environment's complete WebAccessible marker.

## Snowflake and Cortex provider qualification - 2026-08-07

This is sanitized provider/schema evidence, not a completed participant task-run claim.

| Evidence | Result |
|---|---|
| Execution context | `AWS_US_EAST_2`, role `WEBACCESSIBLE_APP_ROLE`; context query `01c63c4c-0107-59ea-000f-e9160001ee4a` |
| Cortex routing | `ANY_REGION`; parameter query `01c63c4c-0107-5622-000f-e91600010022` |
| Model access | `CORTEX_MODELS_ALLOWLIST=All`; parameter query `01c63c4c-0107-59eb-000f-e9160001b192` |
| Exact rate card | `snowflake-cortex-any-region-2026-08-07`: 0.60 AI Credits/1M input, 3.00/1M output, $2.00/AI Credit |
| Rate-card write/readback | MERGE `01c63c4f-0107-5622-000f-e9160001002e` inserted two rows; SELECT `01c63c4f-0107-59eb-000f-e9160001b1a6` returned both |
| Token estimate | `AI_COUNT_TOKENS` query `01c63c53-0107-59eb-000f-e9160001b1aa`: 304 estimated input tokens |
| Structured completion | `AI_COMPLETE` query `01c63c53-0107-500e-0000-000fe91661a9`: `claude-haiku-4-5`, 1,506 prompt, 230 completion, 1,736 total tokens |
| Contract result | Full `GuidanceDecision` validated; target `candidate-lettuce`; ARIA selector role `checkbox`, name `Lettuce`; postcondition `aria-checked=true` |
| Live schema | Ten product tables (`01c63c54-0107-59ea-000f-e9160001ee66`) and eleven evidence views (`01c63c54-0107-59eb-000f-e9160001b1ae`) present |
| Streamlit | `WEBACCESSIBLE_CAREGIVER` exists in `WEBACCESSIBLE.APP`; `SHOW STREAMLITS` query `01c63c54-0107-59ea-000f-e9160001ee6a` |

Rate sources are the [Snowflake Service Consumption Table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf), Table 6(a), effective August 7, 2026, and the [Snowflake Cortex pricing documentation](https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing). The 304-token count is an estimate, not a billing receipt; the provider-returned 1,506/230 usage is the actual cost input. The Streamlit row proves the cloud entity exists, not that a populated participant-run drill-through has been rendered in a browser.

Record build hash, runtime mode, target origin, Browserbase session/create/CDP/Live View/termination references, trusted participant-input timestamp, EverOS Case/Skill/Episode IDs, Snowflake query IDs, Streamlit reference, model/rate-card version, screenshots, and capture time after the first genuine cold and warm runs.
