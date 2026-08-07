USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

-- A matching warm replay is valid only when every successful selector attempt
-- is model-free and the run-level call ledger also contains zero calls.
SELECT
    c.user_id,
    c.task_id,
    c.task_name,
    c.run_id,
    c.run_no,
    c.model_call_count,
    c.actual_model_tokens,
    c.actual_cost_usd,
    COUNT_IF(e.evidence_status = 'zero_model_verified') AS verified_replay_steps,
    COUNT_IF(e.evidence_status = 'model_used') AS replay_steps_with_model,
    IFF(
        c.run_kind = 'warm'
        AND c.model_call_count = 0
        AND COUNT_IF(e.evidence_status = 'model_used') = 0
        AND COUNT_IF(e.evidence_status = 'zero_model_verified') > 0,
        'passes',
        'attention_required'
    ) AS replay_invariant
FROM V_COLD_WARM_COST_CURVE AS c
LEFT JOIN V_SELECTOR_REPLAY_EVIDENCE AS e
    ON e.run_id = c.run_id
WHERE c.run_kind = 'warm'
GROUP BY
    c.user_id,
    c.task_id,
    c.task_name,
    c.run_id,
    c.run_no,
    c.run_kind,
    c.model_call_count,
    c.actual_model_tokens,
    c.actual_cost_usd
ORDER BY c.user_id, c.task_id, c.run_no;
