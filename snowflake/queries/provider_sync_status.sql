USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

SELECT
    started_at,
    user_id,
    task_name,
    mode,
    terminal_outcome,
    browserbase_status,
    cdp_attached_at,
    live_view_ready_at,
    first_trusted_user_action_at,
    terminated_at,
    agent_surface_used,
    telemetry_status,
    step_row_count,
    distinct_event_count,
    ingestion_pending_count,
    ingestion_failed_count,
    everos_provider_status,
    everos_indexing_status,
    model_call_count,
    model_call_failure_count,
    is_verified,
    run_id,
    browserbase_session_id,
    everos_skill_id
FROM V_PROVIDER_SYNC_STATUS
ORDER BY started_at DESC;
