# WebAccessible Data Map

| Data | Source | Purpose | Destination | Retention / deletion |
|---|---|---|---|---|
| Participant name and accessibility preferences | Setup | Adapt visible guidance | EverOS profile; active participant session | Caregiver-managed memory deletion; session copy expires |
| Caregiver mobile | Setup | Future escalation delivery | EverOS reviewed profile only | Never written to logs or Snowflake; deleted with profile |
| Browserbase session ID and lifecycle | Browserbase | Own and terminate the managed browser | Operational store and Snowflake `BROWSER_SESSIONS` | Retained as provider evidence without provider keys or URLs |
| Sanitized element candidate | Live page | Ground one next-step decision | Active process only | Expires with the browser session |
| Trusted action and verification facts | Browserbase Live View | Advance or record one route step | Operational event ledger, Snowflake, EverOS trajectory | No form values, cookies, query strings, or raw DOM |
| Canonical route | Verified teach run | Deterministic warm replay | EverOS `agent_skill` | Versioned and caregiver-readable; deleted through memory workflow |
| Completion statement | Verified terminal predicate | Answer completion questions | EverOS `episode` | Never written for an unverified outcome |
| Sanitized activity observation | Accepted managed-session event | Explain what happened and learn usual task timing | Operational event/index cache; summarized EverOS episode/foresight | Only with activity-memory permission; origin only, no path/query/content; caregiver-readable deletion workflow |
| Routine timing pattern and reminder action | Consented task starts; accept/dismiss | Offer an in-app routine near the usual time and enforce snooze/permission | Operational derived cache; pattern summary in EverOS | Recomputed from consented observations; never authorizes clicks, typing, or submit |
| Model token usage and cost | Snowflake Cortex response | Prove cold/warm economics | Snowflake product tables | Effective rate-card lineage retained with the call |

Passwords, card/CVV data, SSNs, bank-account values, cookies, authentication tokens, full query strings, raw DOM, and input values are excluded at capture time.
