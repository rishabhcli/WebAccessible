# Sponsor and Execution Provider Documentation

These documents convert the sponsor commitments in [SPONSORS.md](../../SPONSORS.md) into buildable contracts. They describe only the behavior that must exist on a live backend path before it is mentioned in a demo or submission.

| Sponsor | Implementation contract | Evidence document |
|---|---|---|
| Snowflake | System of record, measured cost proof, Cortex analytics, and caregiver reporting. | [SNOWFLAKE.md](SNOWFLAKE.md) |
| EverMind / EverOS | Persistent profiles, facts, recorded cases, replay skills, completion episodes, and foresight. | [EVEROS.md](EVEROS.md) |
| Beta Fund | Accurate program framing, sponsor credit, and a deadline-ready proof package. | [BETA_FUND.md](BETA_FUND.md) |
| Browserbase | The sole managed browser-execution environment; Browser Sessions, CDP, and interactive Live View only. | [BROWSERBASE.md](BROWSERBASE.md) |

## Claim standard

Do not call a sponsor integrated because a package, credential, or local mock exists. A claim requires a demonstrated live path, its named evidence artifact, and a visible failure state when that path is unavailable. This rule applies to the WebAccessible session UI, Browserbase bridge, backend, Streamlit view, recorded backup demo, submission copy, and pitch.

The end-to-end implementation order is defined in [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md).
