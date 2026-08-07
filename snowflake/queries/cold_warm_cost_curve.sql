USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

SELECT
    user_id,
    task_id,
    task_name,
    run_no,
    run_id,
    run_kind,
    started_at,
    terminal_outcome,
    skill_id,
    skill_revision,
    model_call_count,
    actual_model_tokens,
    cost_status,
    actual_cost_usd,
    cold_baseline_usd,
    cost_reduction_ratio
FROM V_COLD_WARM_COST_CURVE
ORDER BY user_id, task_id, run_no;
