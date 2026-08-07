USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

SELECT
    run_id,
    call_id,
    step_id,
    guidance_mode,
    provider,
    model,
    model_version,
    actual_input_tokens,
    actual_cached_input_tokens,
    actual_reasoning_tokens,
    actual_output_tokens,
    usage_status,
    call_status,
    rate_card_version,
    token_classes,
    rate_source_reference,
    amount_usd,
    calculation_status,
    is_cost_verified,
    requested_at,
    completed_at,
    calculated_at
FROM V_MODEL_COST_LINEAGE
ORDER BY requested_at DESC;
