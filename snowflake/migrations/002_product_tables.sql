USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

CREATE TABLE IF NOT EXISTS SESSION_RUNS (
    run_id STRING,
    session_id STRING,
    user_id STRING,
    task_id STRING,
    task_name STRING,
    mode STRING,
    skill_id STRING,
    skill_revision INTEGER,
    terminal_outcome STRING,
    terminal_provenance STRING,
    verified_amount NUMBER(18, 2),
    verified_currency STRING,
    source_environment STRING,
    fixture_mode BOOLEAN DEFAULT FALSE,
    build_commit STRING,
    browserbase_session_id STRING,
    everos_case_id STRING,
    everos_skill_id STRING,
    everos_episode_id STRING,
    sync_status STRING,
    started_at TIMESTAMP_NTZ,
    ended_at TIMESTAMP_NTZ,
    last_synced_at TIMESTAMP_NTZ,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'One product-owned row per WebAccessible task run.';

CREATE TABLE IF NOT EXISTS BROWSER_SESSIONS (
    browserbase_session_id STRING,
    session_id STRING,
    run_id STRING,
    user_id STRING,
    region STRING,
    provider_status STRING,
    terminal_reason STRING,
    provider_limit_state STRING,
    agent_surface_used BOOLEAN DEFAULT FALSE,
    source_environment STRING,
    sync_status STRING,
    created_at TIMESTAMP_NTZ,
    cdp_attached_at TIMESTAMP_NTZ,
    live_view_ready_at TIMESTAMP_NTZ,
    first_trusted_user_action_at TIMESTAMP_NTZ,
    terminate_requested_at TIMESTAMP_NTZ,
    terminated_at TIMESTAMP_NTZ,
    last_provider_check_at TIMESTAMP_NTZ,
    last_synced_at TIMESTAMP_NTZ,
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Browserbase lifecycle facts without API keys, CDP URLs, or Live View URLs.';

CREATE TABLE IF NOT EXISTS MODEL_CALLS (
    call_id STRING,
    session_id STRING,
    run_id STRING,
    user_id STRING,
    event_id STRING,
    step_id STRING,
    guidance_mode STRING,
    provider STRING,
    model STRING,
    model_version STRING,
    estimated_input_tokens INTEGER,
    actual_input_tokens INTEGER,
    actual_cached_input_tokens INTEGER,
    actual_reasoning_tokens INTEGER,
    actual_output_tokens INTEGER,
    usage_status STRING,
    latency_ms INTEGER,
    status STRING,
    provider_response_id_hash STRING,
    source_environment STRING,
    requested_at TIMESTAMP_NTZ,
    completed_at TIMESTAMP_NTZ,
    synchronized_at TIMESTAMP_NTZ,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Immutable model and Cortex call ledger with provider-returned usage.';

CREATE TABLE IF NOT EXISTS COST_RATE_CARDS (
    rate_card_id STRING,
    rate_card_version STRING,
    provider STRING,
    model STRING,
    model_version STRING,
    token_class STRING,
    unit_quantity NUMBER(38, 0),
    unit_price NUMBER(38, 12),
    currency STRING,
    usd_conversion_rate NUMBER(38, 12),
    source_reference STRING,
    rounding_rule STRING,
    effective_from TIMESTAMP_NTZ,
    effective_to TIMESTAMP_NTZ,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Effective-dated immutable model rate cards; no inferred or guessed prices.';

CREATE TABLE IF NOT EXISTS MODEL_COSTS (
    cost_id STRING,
    call_id STRING,
    session_id STRING,
    run_id STRING,
    user_id STRING,
    rate_card_version STRING,
    actual_input_tokens INTEGER,
    actual_cached_input_tokens INTEGER,
    actual_reasoning_tokens INTEGER,
    actual_output_tokens INTEGER,
    input_amount NUMBER(38, 12),
    cached_input_amount NUMBER(38, 12),
    reasoning_amount NUMBER(38, 12),
    output_amount NUMBER(38, 12),
    credits NUMBER(38, 12),
    amount_currency NUMBER(38, 12),
    currency STRING,
    amount_usd NUMBER(38, 12),
    calculation_status STRING,
    source_environment STRING,
    calculated_at TIMESTAMP_NTZ,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Calculated per-call model cost linked to actual usage and a rate-card version.';

CREATE TABLE IF NOT EXISTS TELEMETRY_INGESTION (
    event_id STRING,
    session_id STRING,
    run_id STRING,
    user_id STRING,
    target_table STRING,
    payload_hash STRING,
    source_environment STRING,
    status STRING,
    attempt_count INTEGER,
    first_attempt_at TIMESTAMP_NTZ,
    last_attempt_at TIMESTAMP_NTZ,
    synchronized_at TIMESTAMP_NTZ,
    last_error_code STRING,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Idempotent outbox synchronization and reconciliation ledger keyed by event ID.';

CREATE TABLE IF NOT EXISTS ESCALATIONS (
    escalation_id STRING,
    session_id STRING,
    run_id STRING,
    user_id STRING,
    reason STRING,
    status STRING,
    delivery_channel STRING,
    delivery_attempt_count INTEGER,
    delivery_attempted_at TIMESTAMP_NTZ,
    delivery_receipt_at TIMESTAMP_NTZ,
    provider_message_id_hash STRING,
    caregiver_response_status STRING,
    caregiver_response_metadata VARIANT,
    caregiver_response_at TIMESTAMP_NTZ,
    source_environment STRING,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Escalation lifecycle and delivery receipt facts without caregiver contact details.';

CREATE TABLE IF NOT EXISTS SKILL_REVISION_LINKS (
    skill_revision_link_id STRING,
    skill_key STRING,
    revision INTEGER,
    everos_skill_id STRING,
    everos_case_id STRING,
    source_session_id STRING,
    source_run_id STRING,
    source_step_id STRING,
    parent_revision INTEGER,
    task_outcome STRING,
    repair_reason STRING,
    provider_status STRING,
    indexing_status STRING,
    is_current BOOLEAN,
    source_environment STRING,
    written_at TIMESTAMP_NTZ,
    retrieved_at TIMESTAMP_NTZ,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'EverOS skill revision lineage without duplicating the full skill body.';

ALTER TABLE SKILL_REVISION_LINKS
    ADD COLUMN IF NOT EXISTS skill_revision_link_id STRING;

CREATE TABLE IF NOT EXISTS SELECTOR_ATTEMPTS (
    selector_attempt_id STRING,
    event_id STRING,
    session_id STRING,
    run_id STRING,
    user_id STRING,
    step_id STRING,
    attempt_no INTEGER,
    selector_tier STRING,
    selector_fingerprint STRING,
    resolution_result STRING,
    matched_candidate_count INTEGER,
    verification_predicate STRING,
    verification_result STRING,
    trusted_user_action BOOLEAN,
    replayed_from_memory BOOLEAN,
    model_call_id STRING,
    source_environment STRING,
    observed_at TIMESTAMP_NTZ,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Ordered selector resolution and verification evidence for replay and repair.';
