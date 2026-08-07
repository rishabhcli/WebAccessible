USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

WITH latest_run AS (
    SELECT run_id
    FROM V_VERIFIED_SESSION_RUNS
    ORDER BY started_at DESC
    LIMIT 1
)
SELECT
    t.occurred_at,
    t.step_no,
    t.action,
    t.guidance_mode,
    t.outcome,
    t.replayed_from_memory,
    t.trusted_user_action,
    t.selector_tier,
    t.selector_result,
    t.verification_predicate,
    t.verification_result,
    t.model_used,
    t.input_tokens,
    t.output_tokens,
    t.latency_ms,
    t.event_id,
    t.step_id
FROM V_SESSION_TIMELINE AS t
INNER JOIN latest_run AS r ON r.run_id = t.run_id
ORDER BY t.step_no, t.occurred_at;
