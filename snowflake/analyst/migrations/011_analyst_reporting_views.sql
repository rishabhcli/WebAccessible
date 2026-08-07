-- WebAccessible Cortex Analyst caregiver reporting: redacted projection views.
--
-- Every view below reads only from the product-owned verified views created by
-- snowflake/migrations/003_evidence_views.sql. No view reads a base table directly, so
-- fixture rows and unsynchronized rows cannot reach the semantic model: the upstream
-- views already restrict source_environment to demo/production, exclude fixture_mode,
-- and gate on the is_verified / run_is_verified / is_cost_verified predicates.
--
-- Column allowlist policy (docs/privacy-data-map.md and IMPLEMENTATION_PLAN.md 6.6).
-- These columns are deliberately NOT projected into the Analyst layer:
--
--   verification_predicate   May embed expected page text captured from the live DOM.
--   selector_fingerprint     May encode DOM attribute values or accessible-name text.
--   provider_response_id_hash, provider_message_id_hash, payload_hash
--                            Provider correlation hashes with no caregiver meaning.
--   caregiver_response_metadata
--                            Free-form VARIANT; not exposed to a text-to-SQL surface.
--   SESSION_STEPS.model_used / input_tokens / output_tokens / latency_ms
--                            The step ledger records zeros for observed events. Actual
--                            model usage is authoritative only in MODEL_CALLS, so usage
--                            and latency are exposed exclusively through V_CAREGIVER_MODEL_USAGE.
--   MODEL_COSTS.amount_usd (raw)
--                            Exposed only as verified_cost_usd, which is NULL unless the
--                            call has actual provider usage, a calculated MODEL_COSTS row,
--                            and a matched COST_RATE_CARDS row.
--
-- Raw DOM text, model prompts, uploaded documents, phone numbers, account numbers,
-- credentials, and full URLs are absent from the upstream product tables by construction;
-- url_domain carries the origin host only and is projected as site_domain.

USE DATABASE WEBACCESSIBLE;
USE SCHEMA ANALYST;

CREATE OR REPLACE VIEW V_CAREGIVER_SESSION
    COMMENT = 'One row per verified WebAccessible task run, with verified outcome and verified cost status.'
AS
SELECT
    c.run_id,
    c.session_id,
    c.user_id,
    c.task_id,
    c.task_name,
    c.run_no,
    c.run_kind,
    c.mode,
    c.terminal_outcome,
    c.terminal_provenance,
    c.verified_amount,
    c.verified_currency,
    c.started_at,
    c.ended_at,
    DATEDIFF('second', c.started_at, c.ended_at) AS duration_seconds,
    c.last_model_call_at,
    c.skill_id,
    c.skill_revision,
    c.everos_case_id,
    c.everos_skill_id,
    c.everos_episode_id,
    c.browserbase_session_id,
    c.browserbase_region,
    c.browserbase_status,
    c.build_commit,
    c.model_call_count,
    c.priced_call_count,
    c.actual_model_tokens,
    c.cost_status,
    -- NULL whenever any contributing call is unpriced; never an inferred amount.
    c.actual_cost_usd,
    c.cold_baseline_usd,
    c.cost_reduction_ratio,
    IFF(c.terminal_outcome = 'completed', 1, 0) AS completed_session,
    IFF(c.terminal_outcome = 'prepared', 1, 0) AS prepared_session,
    IFF(c.run_kind = 'cold', 1, 0) AS cold_session,
    IFF(c.run_kind = 'warm', 1, 0) AS warm_session,
    IFF(c.run_kind = 'repair', 1, 0) AS repair_session,
    IFF(c.cost_status IN ('verified', 'verified_zero'), 1, 0) AS cost_verified_session,
    IFF(c.cost_status = 'unavailable', 1, 0) AS cost_unavailable_session
FROM WEBACCESSIBLE.APP.V_COLD_WARM_COST_CURVE AS c
WHERE c.is_verified;

CREATE OR REPLACE VIEW V_CAREGIVER_ASSISTANCE_EVENT
    COMMENT = 'One row per assistance step inside a verified run. Behavior only; model usage lives in V_CAREGIVER_MODEL_USAGE.'
AS
SELECT
    t.run_id,
    t.session_id,
    t.event_id,
    t.step_id,
    t.step_no,
    t.occurred_at,
    t.synchronized_at,
    t.task_id,
    t.task_name,
    t.url_domain AS site_domain,
    t.action AS event_action,
    t.guidance_mode,
    t.outcome,
    t.replayed_from_memory,
    t.trusted_user_action,
    t.selector_tier,
    t.selector_result,
    t.verification_result,
    t.run_mode,
    t.terminal_outcome,
    IFF(t.replayed_from_memory, 1, 0) AS replayed_step,
    IFF(t.outcome = 'ok', 1, 0) AS ok_step,
    IFF(t.outcome = 'stuck', 1, 0) AS stuck_step,
    IFF(t.outcome = 'wrong_click', 1, 0) AS wrong_click_step,
    IFF(t.outcome = 'escalated', 1, 0) AS escalated_step,
    IFF(t.trusted_user_action, 1, 0) AS trusted_user_action_step,
    IFF(t.model_call_id IS NOT NULL, 1, 0) AS model_assisted_step
FROM WEBACCESSIBLE.APP.V_SESSION_TIMELINE AS t
WHERE t.run_is_verified;

CREATE OR REPLACE VIEW V_CAREGIVER_MODEL_USAGE
    COMMENT = 'One row per model call in a verified run, with provider-reported actual usage and rate-card-backed verified cost.'
AS
SELECT
    l.call_id,
    l.run_id,
    l.session_id,
    l.event_id,
    l.step_id,
    l.guidance_mode,
    l.provider,
    l.model,
    l.model_version,
    l.actual_input_tokens,
    l.actual_cached_input_tokens,
    l.actual_reasoning_tokens,
    l.actual_output_tokens,
    COALESCE(l.actual_input_tokens, 0)
        + COALESCE(l.actual_cached_input_tokens, 0)
        + COALESCE(l.actual_reasoning_tokens, 0)
        + COALESCE(l.actual_output_tokens, 0) AS actual_total_tokens,
    l.usage_status,
    l.call_status,
    l.latency_ms,
    l.requested_at,
    l.completed_at,
    l.rate_card_version,
    l.rate_source_reference,
    l.token_classes,
    l.rate_effective_from,
    l.rate_effective_to,
    l.calculation_status,
    l.is_cost_verified,
    -- is_cost_verified upstream requires usage_status = 'actual', a single calculated
    -- MODEL_COSTS row with a non-null amount_usd, and at least one matching
    -- COST_RATE_CARDS row for the exact provider/model/version and rate card version.
    -- An unpriced call therefore reports NULL cost, never an estimate.
    IFF(l.is_cost_verified, l.amount_usd, NULL) AS verified_cost_usd,
    IFF(l.is_cost_verified, 1, 0) AS priced_call,
    IFF(l.is_cost_verified, 0, 1) AS unpriced_call
FROM WEBACCESSIBLE.APP.V_MODEL_COST_LINEAGE AS l
INNER JOIN WEBACCESSIBLE.APP.V_VERIFIED_SESSION_RUNS AS r
    ON r.run_id = l.run_id;

CREATE OR REPLACE VIEW V_CAREGIVER_REPLAY_EVIDENCE
    COMMENT = 'One row per selector resolution attempt in a verified run, without selector fingerprints or page predicates.'
AS
SELECT
    e.selector_attempt_id,
    e.run_id,
    e.session_id,
    e.event_id,
    e.step_id,
    e.attempt_no,
    e.selector_tier,
    e.resolution_result,
    e.matched_candidate_count,
    e.verification_result,
    e.trusted_user_action,
    e.replayed_from_memory,
    e.evidence_status,
    e.observed_at,
    e.run_mode,
    e.skill_id,
    e.skill_revision,
    IFF(e.evidence_status = 'zero_model_verified', 1, 0) AS zero_model_verified_attempt,
    IFF(e.resolution_result = 'matched', 1, 0) AS selector_matched_attempt,
    IFF(e.verification_result = 'verified', 1, 0) AS verified_attempt,
    IFF(e.model_call_id IS NOT NULL, 1, 0) AS model_assisted_attempt
FROM WEBACCESSIBLE.APP.V_SELECTOR_REPLAY_EVIDENCE AS e
WHERE e.run_is_verified;

CREATE OR REPLACE VIEW V_CAREGIVER_PROVIDER_SYNC
    COMMENT = 'One row per verified run describing Browserbase, EverOS, and telemetry synchronization state.'
AS
SELECT
    p.run_id,
    p.session_id,
    p.telemetry_status,
    p.run_sync_status,
    p.browserbase_session_id,
    p.browserbase_status,
    p.provider_limit_state,
    p.agent_surface_used,
    p.cdp_attached_at,
    p.live_view_ready_at,
    p.first_trusted_user_action_at,
    p.terminated_at AS browser_terminated_at,
    p.step_row_count,
    p.distinct_event_count,
    p.missing_event_id_count,
    p.ingestion_row_count,
    p.ingestion_synced_count,
    p.ingestion_pending_count,
    p.ingestion_failed_count,
    p.model_call_count,
    p.model_call_failure_count,
    p.last_step_sync_at,
    p.last_ingestion_attempt_at,
    p.last_model_sync_at,
    p.everos_provider_status,
    p.everos_indexing_status,
    p.everos_retrieved_at,
    IFF(p.telemetry_status = 'synced', 1, 0) AS synced_run,
    IFF(p.ingestion_pending_count > 0, 1, 0) AS pending_ingestion_run,
    IFF(p.ingestion_failed_count > 0, 1, 0) AS failed_ingestion_run
FROM WEBACCESSIBLE.APP.V_PROVIDER_SYNC_STATUS AS p
WHERE p.is_verified;

CREATE OR REPLACE VIEW V_CAREGIVER_ESCALATION
    COMMENT = 'One row per escalation raised inside a verified run, without caregiver contact details or provider message hashes.'
AS
SELECT
    e.escalation_id,
    e.run_id,
    e.session_id,
    e.reason,
    e.status,
    e.delivery_channel,
    e.delivery_attempt_count,
    e.delivery_attempted_at,
    e.delivery_receipt_at,
    e.caregiver_response_status,
    e.caregiver_response_at,
    e.created_at,
    IFF(e.status IN ('delivered', 'acknowledged', 'resolved'), 1, 0) AS delivered_escalation,
    IFF(e.status = 'delivery_failed', 1, 0) AS failed_delivery_escalation,
    IFF(e.status IN ('pending', 'delivered', 'delivery_failed'), 1, 0) AS unresolved_escalation
FROM WEBACCESSIBLE.APP.V_ESCALATION_OVERVIEW AS e
WHERE e.run_is_verified;
