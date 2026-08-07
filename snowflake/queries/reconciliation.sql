USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

SELECT
    run_id,
    session_id,
    user_id,
    task_name,
    mode,
    step_rows,
    distinct_events,
    incomplete_step_rows,
    invalid_outcome_rows,
    invalid_guidance_mode_rows,
    duplicate_call_ids,
    duplicate_cost_call_ids,
    run_row_count,
    browser_row_count,
    sync_status,
    is_verified,
    reconciliation_status
FROM V_TELEMETRY_RECONCILIATION
WHERE reconciliation_status <> 'clean'
   OR NOT is_verified
ORDER BY task_name, run_id;
