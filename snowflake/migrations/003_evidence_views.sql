USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

CREATE OR REPLACE VIEW V_SESSION_OVERVIEW AS
WITH run_rows AS (
    SELECT
        r.*,
        COUNT(*) OVER (PARTITION BY run_id) AS run_row_count,
        ROW_NUMBER() OVER (
            PARTITION BY run_id
            ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
        ) AS row_rank
    FROM SESSION_RUNS AS r
),
browser_rows AS (
    SELECT
        b.*,
        COUNT(*) OVER (PARTITION BY browserbase_session_id) AS browser_row_count,
        ROW_NUMBER() OVER (
            PARTITION BY browserbase_session_id
            ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
        ) AS row_rank
    FROM BROWSER_SESSIONS AS b
)
SELECT
    r.run_id,
    r.session_id,
    r.user_id,
    r.task_id,
    r.task_name,
    r.mode,
    r.skill_id,
    r.skill_revision,
    r.terminal_outcome,
    r.terminal_provenance,
    r.verified_amount,
    r.verified_currency,
    r.source_environment,
    r.fixture_mode,
    r.build_commit,
    r.everos_case_id,
    r.everos_skill_id,
    r.everos_episode_id,
    r.sync_status,
    r.started_at,
    r.ended_at,
    r.last_synced_at,
    b.browserbase_session_id,
    b.region AS browserbase_region,
    b.provider_status AS browserbase_status,
    b.provider_limit_state,
    b.agent_surface_used,
    b.created_at AS browser_created_at,
    b.cdp_attached_at,
    b.live_view_ready_at,
    b.first_trusted_user_action_at,
    b.terminate_requested_at,
    b.terminated_at,
    b.terminal_reason AS browser_terminal_reason,
    r.run_row_count,
    COALESCE(b.browser_row_count, 0) AS browser_row_count,
    IFF(
        r.run_row_count = 1
        AND COALESCE(b.browser_row_count, 0) = 1
        AND r.source_environment IN ('demo', 'production')
        AND COALESCE(r.fixture_mode, FALSE) = FALSE
        AND r.run_id IS NOT NULL
        AND r.session_id IS NOT NULL
        AND r.user_id IS NOT NULL
        AND r.task_id IS NOT NULL
        AND r.task_name IS NOT NULL
        AND r.sync_status = 'synced'
        AND r.terminal_outcome IN ('completed', 'prepared')
        AND r.terminal_provenance IS NOT NULL
        AND r.build_commit IS NOT NULL
        AND r.started_at IS NOT NULL
        AND r.ended_at IS NOT NULL
        AND r.everos_skill_id IS NOT NULL
        AND b.browserbase_session_id IS NOT NULL
        AND b.cdp_attached_at IS NOT NULL
        AND b.live_view_ready_at IS NOT NULL
        AND b.first_trusted_user_action_at IS NOT NULL
        AND b.terminated_at IS NOT NULL
        AND b.provider_status IN ('COMPLETED', 'TERMINATED', 'completed', 'terminated')
        AND COALESCE(b.agent_surface_used, FALSE) = FALSE,
        TRUE,
        FALSE
    ) AS is_verified
FROM run_rows AS r
LEFT JOIN browser_rows AS b
    ON b.browserbase_session_id = r.browserbase_session_id
    AND b.row_rank = 1
WHERE r.row_rank = 1
  AND r.source_environment IN ('demo', 'production')
  AND COALESCE(r.fixture_mode, FALSE) = FALSE;

CREATE OR REPLACE VIEW V_VERIFIED_SESSION_RUNS AS
SELECT *
FROM V_SESSION_OVERVIEW
WHERE is_verified;

CREATE OR REPLACE VIEW V_SESSION_TIMELINE AS
SELECT
    s.run_id,
    s.session_id,
    s.event_id,
    s.step_id,
    s.step_no,
    s.ts AS occurred_at,
    s.task_id,
    s.task_name,
    s.url_domain,
    s.action,
    s.guidance_mode,
    s.outcome,
    s.replayed_from_memory,
    s.trusted_user_action,
    s.selector_tier,
    s.selector_result,
    s.verification_predicate,
    s.verification_result,
    s.model_call_id,
    s.model_used,
    s.input_tokens,
    s.output_tokens,
    s.latency_ms,
    s.synchronized_at,
    o.user_id,
    o.mode AS run_mode,
    o.terminal_outcome,
    o.is_verified AS run_is_verified,
    IFF(
        s.event_id IS NULL,
        NULL,
        COUNT(*) OVER (PARTITION BY s.event_id)
    ) AS event_row_count
FROM SESSION_STEPS AS s
INNER JOIN V_SESSION_OVERVIEW AS o
    ON o.run_id = s.run_id
WHERE s.source_environment IN ('demo', 'production');

CREATE OR REPLACE VIEW V_MODEL_COST_LINEAGE AS
WITH call_rows AS (
    SELECT
        c.*,
        COUNT(*) OVER (PARTITION BY call_id) AS call_row_count,
        ROW_NUMBER() OVER (
            PARTITION BY call_id
            ORDER BY completed_at DESC NULLS LAST, created_at DESC NULLS LAST
        ) AS row_rank
    FROM MODEL_CALLS AS c
    WHERE source_environment IN ('demo', 'production')
),
cost_rows AS (
    SELECT
        c.*,
        COUNT(*) OVER (PARTITION BY call_id) AS cost_row_count,
        ROW_NUMBER() OVER (
            PARTITION BY call_id
            ORDER BY calculated_at DESC NULLS LAST, created_at DESC NULLS LAST
        ) AS row_rank
    FROM MODEL_COSTS AS c
    WHERE source_environment IN ('demo', 'production')
),
rate_card_summary AS (
    SELECT
        rate_card_version,
        provider,
        model,
        model_version,
        LISTAGG(DISTINCT token_class, ', ') WITHIN GROUP (ORDER BY token_class) AS token_classes,
        MIN(effective_from) AS effective_from,
        MAX(effective_to) AS effective_to,
        MAX(source_reference) AS source_reference,
        COUNT(*) AS rate_row_count
    FROM COST_RATE_CARDS
    GROUP BY rate_card_version, provider, model, model_version
)
SELECT
    c.call_id,
    c.session_id,
    c.run_id,
    c.user_id,
    c.event_id,
    c.step_id,
    c.guidance_mode,
    c.provider,
    c.model,
    c.model_version,
    c.estimated_input_tokens,
    c.actual_input_tokens,
    c.actual_cached_input_tokens,
    c.actual_reasoning_tokens,
    c.actual_output_tokens,
    c.usage_status,
    c.latency_ms,
    c.status AS call_status,
    c.provider_response_id_hash,
    c.requested_at,
    c.completed_at,
    c.synchronized_at,
    c.call_row_count,
    k.cost_id,
    k.rate_card_version,
    k.input_amount,
    k.cached_input_amount,
    k.reasoning_amount,
    k.output_amount,
    k.credits,
    k.amount_currency,
    k.currency,
    k.amount_usd,
    k.calculation_status,
    k.calculated_at,
    COALESCE(k.cost_row_count, 0) AS cost_row_count,
    r.token_classes,
    r.effective_from AS rate_effective_from,
    r.effective_to AS rate_effective_to,
    r.source_reference AS rate_source_reference,
    COALESCE(r.rate_row_count, 0) AS rate_row_count,
    IFF(
        c.call_row_count = 1
        AND COALESCE(k.cost_row_count, 0) = 1
        AND c.usage_status = 'actual'
        AND c.status IN ('completed', 'succeeded', 'ok')
        AND k.calculation_status = 'calculated'
        AND k.amount_usd IS NOT NULL
        AND COALESCE(r.rate_row_count, 0) > 0,
        TRUE,
        FALSE
    ) AS is_cost_verified
FROM call_rows AS c
LEFT JOIN cost_rows AS k
    ON k.call_id = c.call_id
    AND k.row_rank = 1
LEFT JOIN rate_card_summary AS r
    ON r.rate_card_version = k.rate_card_version
    AND r.provider = c.provider
    AND r.model = c.model
    AND COALESCE(r.model_version, '') = COALESCE(c.model_version, '')
WHERE c.row_rank = 1;

CREATE OR REPLACE VIEW V_RUN_COSTS AS
WITH call_rollup AS (
    SELECT
        run_id,
        COUNT(*) AS model_call_count,
        COUNT_IF(is_cost_verified) AS priced_call_count,
        SUM(
            COALESCE(actual_input_tokens, 0)
            + COALESCE(actual_cached_input_tokens, 0)
            + COALESCE(actual_reasoning_tokens, 0)
            + COALESCE(actual_output_tokens, 0)
        ) AS actual_model_tokens,
        SUM(IFF(is_cost_verified, amount_usd, 0)) AS verified_cost_usd,
        MAX(completed_at) AS last_model_call_at
    FROM V_MODEL_COST_LINEAGE
    GROUP BY run_id
),
joined AS (
    SELECT
        r.*,
        COALESCE(c.model_call_count, 0) AS model_call_count,
        COALESCE(c.priced_call_count, 0) AS priced_call_count,
        COALESCE(c.actual_model_tokens, 0) AS actual_model_tokens,
        c.verified_cost_usd,
        c.last_model_call_at
    FROM V_VERIFIED_SESSION_RUNS AS r
    LEFT JOIN call_rollup AS c
        ON c.run_id = r.run_id
)
SELECT
    j.*,
    CASE
        WHEN model_call_count = 0 THEN 'verified_zero'
        WHEN model_call_count = priced_call_count THEN 'verified'
        ELSE 'unavailable'
    END AS cost_status,
    CASE
        WHEN model_call_count = 0 THEN 0::NUMBER(38, 12)
        WHEN model_call_count = priced_call_count THEN verified_cost_usd
        ELSE NULL
    END AS actual_cost_usd
FROM joined AS j;

CREATE OR REPLACE VIEW V_COLD_WARM_COST_CURVE AS
WITH ordered_runs AS (
    SELECT
        c.*,
        CASE
            WHEN mode IN ('cold', 'cold_teach', 'caregiver_record', 'record') THEN 'cold'
            WHEN mode = 'replay' THEN 'warm'
            WHEN mode = 'repair' THEN 'repair'
            ELSE 'other'
        END AS run_kind,
        ROW_NUMBER() OVER (
            PARTITION BY user_id, task_id
            ORDER BY started_at, run_id
        ) AS run_no
    FROM V_RUN_COSTS AS c
),
baselined AS (
    SELECT
        o.*,
        MAX(
            IFF(
                run_no = 1
                AND run_kind = 'cold'
                AND cost_status IN ('verified', 'verified_zero'),
                actual_cost_usd,
                NULL
            )
        ) OVER (PARTITION BY user_id, task_id) AS cold_baseline_usd
    FROM ordered_runs AS o
)
SELECT
    b.*,
    IFF(
        cold_baseline_usd > 0
        AND actual_cost_usd IS NOT NULL,
        (cold_baseline_usd - actual_cost_usd) / cold_baseline_usd,
        NULL
    ) AS cost_reduction_ratio
FROM baselined AS b;

CREATE OR REPLACE VIEW V_SELECTOR_REPLAY_EVIDENCE AS
WITH attempt_rows AS (
    SELECT
        a.*,
        COUNT(*) OVER (PARTITION BY selector_attempt_id) AS attempt_row_count,
        ROW_NUMBER() OVER (
            PARTITION BY selector_attempt_id
            ORDER BY observed_at DESC NULLS LAST, created_at DESC NULLS LAST
        ) AS row_rank
    FROM SELECTOR_ATTEMPTS AS a
    WHERE source_environment IN ('demo', 'production')
)
SELECT
    a.selector_attempt_id,
    a.event_id,
    a.session_id,
    a.run_id,
    a.user_id,
    a.step_id,
    a.attempt_no,
    a.selector_tier,
    a.selector_fingerprint,
    a.resolution_result,
    a.matched_candidate_count,
    a.verification_predicate,
    a.verification_result,
    a.trusted_user_action,
    a.replayed_from_memory,
    a.model_call_id,
    a.observed_at,
    a.attempt_row_count,
    o.task_id,
    o.task_name,
    o.mode AS run_mode,
    o.skill_id,
    o.skill_revision,
    o.is_verified AS run_is_verified,
    CASE
        WHEN a.replayed_from_memory
            AND a.model_call_id IS NULL
            AND a.resolution_result = 'matched'
            AND a.verification_result = 'verified'
            AND a.trusted_user_action
            THEN 'zero_model_verified'
        WHEN a.replayed_from_memory AND a.model_call_id IS NOT NULL THEN 'model_used'
        WHEN a.resolution_result <> 'matched' THEN 'selector_failed'
        WHEN a.verification_result <> 'verified' THEN 'verification_failed'
        ELSE 'observed'
    END AS evidence_status
FROM attempt_rows AS a
INNER JOIN V_SESSION_OVERVIEW AS o
    ON o.run_id = a.run_id
WHERE a.row_rank = 1;

CREATE OR REPLACE VIEW V_PROVIDER_SYNC_STATUS AS
WITH step_totals AS (
    SELECT
        run_id,
        COUNT(*) AS step_row_count,
        COUNT(DISTINCT event_id) AS distinct_event_count,
        COUNT_IF(event_id IS NULL) AS missing_event_id_count,
        MAX(synchronized_at) AS last_step_sync_at
    FROM SESSION_STEPS
    WHERE source_environment IN ('demo', 'production')
    GROUP BY run_id
),
ingestion_totals AS (
    SELECT
        run_id,
        COUNT(*) AS ingestion_row_count,
        COUNT_IF(status = 'synced') AS ingestion_synced_count,
        COUNT_IF(status IN ('pending', 'retrying')) AS ingestion_pending_count,
        COUNT_IF(status = 'failed') AS ingestion_failed_count,
        MAX(last_attempt_at) AS last_ingestion_attempt_at
    FROM TELEMETRY_INGESTION
    WHERE source_environment IN ('demo', 'production')
    GROUP BY run_id
),
model_totals AS (
    SELECT
        run_id,
        COUNT(*) AS model_call_count,
        COUNT_IF(status NOT IN ('completed', 'succeeded', 'ok')) AS model_call_failure_count,
        MAX(synchronized_at) AS last_model_sync_at
    FROM MODEL_CALLS
    WHERE source_environment IN ('demo', 'production')
    GROUP BY run_id
),
skill_rows AS (
    SELECT
        source_run_id AS run_id,
        everos_case_id,
        everos_skill_id,
        revision,
        provider_status,
        indexing_status,
        retrieved_at,
        ROW_NUMBER() OVER (
            PARTITION BY source_run_id
            ORDER BY is_current DESC NULLS LAST, revision DESC, created_at DESC
        ) AS row_rank
    FROM SKILL_REVISION_LINKS
    WHERE source_environment IN ('demo', 'production')
)
SELECT
    o.run_id,
    o.session_id,
    o.user_id,
    o.task_id,
    o.task_name,
    o.mode,
    o.terminal_outcome,
    o.started_at,
    o.ended_at,
    o.sync_status AS run_sync_status,
    o.browserbase_session_id,
    o.browserbase_status,
    o.provider_limit_state,
    o.cdp_attached_at,
    o.live_view_ready_at,
    o.first_trusted_user_action_at,
    o.terminated_at,
    o.agent_surface_used,
    COALESCE(s.step_row_count, 0) AS step_row_count,
    COALESCE(s.distinct_event_count, 0) AS distinct_event_count,
    COALESCE(s.missing_event_id_count, 0) AS missing_event_id_count,
    s.last_step_sync_at,
    COALESCE(i.ingestion_row_count, 0) AS ingestion_row_count,
    COALESCE(i.ingestion_synced_count, 0) AS ingestion_synced_count,
    COALESCE(i.ingestion_pending_count, 0) AS ingestion_pending_count,
    COALESCE(i.ingestion_failed_count, 0) AS ingestion_failed_count,
    i.last_ingestion_attempt_at,
    COALESCE(m.model_call_count, 0) AS model_call_count,
    COALESCE(m.model_call_failure_count, 0) AS model_call_failure_count,
    m.last_model_sync_at,
    k.everos_case_id,
    k.everos_skill_id,
    k.revision AS skill_revision,
    k.provider_status AS everos_provider_status,
    k.indexing_status AS everos_indexing_status,
    k.retrieved_at AS everos_retrieved_at,
    o.is_verified,
    CASE
        WHEN COALESCE(i.ingestion_failed_count, 0) > 0 THEN 'failed'
        WHEN COALESCE(i.ingestion_pending_count, 0) > 0 THEN 'pending'
        WHEN o.sync_status = 'synced' THEN 'synced'
        ELSE COALESCE(o.sync_status, 'unknown')
    END AS telemetry_status
FROM V_SESSION_OVERVIEW AS o
LEFT JOIN step_totals AS s ON s.run_id = o.run_id
LEFT JOIN ingestion_totals AS i ON i.run_id = o.run_id
LEFT JOIN model_totals AS m ON m.run_id = o.run_id
LEFT JOIN skill_rows AS k ON k.run_id = o.run_id AND k.row_rank = 1;

CREATE OR REPLACE VIEW V_ESCALATION_OVERVIEW AS
SELECT
    e.escalation_id,
    e.session_id,
    e.run_id,
    e.user_id,
    e.reason,
    e.status,
    e.delivery_channel,
    e.delivery_attempt_count,
    e.delivery_attempted_at,
    e.delivery_receipt_at,
    e.caregiver_response_status,
    e.caregiver_response_at,
    e.created_at,
    e.updated_at,
    o.task_id,
    o.task_name,
    o.terminal_outcome,
    o.is_verified AS run_is_verified
FROM ESCALATIONS AS e
LEFT JOIN V_SESSION_OVERVIEW AS o
    ON o.run_id = e.run_id
WHERE e.source_environment IN ('demo', 'production');

CREATE OR REPLACE VIEW V_SKILL_LINEAGE AS
SELECT
    l.skill_revision_link_id,
    l.skill_key,
    l.revision,
    l.everos_skill_id,
    l.everos_case_id,
    l.source_session_id,
    l.source_run_id,
    l.source_step_id,
    l.parent_revision,
    l.task_outcome,
    l.repair_reason,
    l.provider_status,
    l.indexing_status,
    l.is_current,
    l.written_at,
    l.retrieved_at,
    o.user_id,
    o.task_id,
    o.task_name,
    o.mode AS source_run_mode,
    o.is_verified AS source_run_is_verified
FROM SKILL_REVISION_LINKS AS l
LEFT JOIN V_SESSION_OVERVIEW AS o
    ON o.run_id = l.source_run_id
WHERE l.source_environment IN ('demo', 'production');

CREATE OR REPLACE VIEW V_TELEMETRY_RECONCILIATION AS
WITH step_quality AS (
    SELECT
        run_id,
        COUNT(*) AS step_rows,
        COUNT(DISTINCT event_id) AS distinct_events,
        COUNT_IF(
            event_id IS NULL
            OR session_id IS NULL
            OR run_id IS NULL
            OR user_id IS NULL
            OR step_no IS NULL
            OR replayed_from_memory IS NULL
            OR outcome IS NULL
            OR ts IS NULL
        ) AS incomplete_step_rows,
        COUNT_IF(outcome NOT IN ('ok', 'wrong_click', 'stuck', 'escalated')) AS invalid_outcome_rows,
        COUNT_IF(guidance_mode NOT IN ('cold', 'replay', 'repair', 'none')) AS invalid_guidance_mode_rows
    FROM SESSION_STEPS
    WHERE source_environment IN ('demo', 'production')
    GROUP BY run_id
),
duplicate_calls AS (
    SELECT run_id, COUNT(*) AS duplicate_call_ids
    FROM (
        SELECT run_id, call_id
        FROM MODEL_CALLS
        WHERE source_environment IN ('demo', 'production')
        GROUP BY run_id, call_id
        HAVING COUNT(*) > 1
    )
    GROUP BY run_id
),
duplicate_costs AS (
    SELECT run_id, COUNT(*) AS duplicate_cost_call_ids
    FROM (
        SELECT run_id, call_id
        FROM MODEL_COSTS
        WHERE source_environment IN ('demo', 'production')
        GROUP BY run_id, call_id
        HAVING COUNT(*) > 1
    )
    GROUP BY run_id
)
SELECT
    o.run_id,
    o.session_id,
    o.user_id,
    o.task_id,
    o.task_name,
    o.mode,
    COALESCE(q.step_rows, 0) AS step_rows,
    COALESCE(q.distinct_events, 0) AS distinct_events,
    COALESCE(q.incomplete_step_rows, 0) AS incomplete_step_rows,
    COALESCE(q.invalid_outcome_rows, 0) AS invalid_outcome_rows,
    COALESCE(q.invalid_guidance_mode_rows, 0) AS invalid_guidance_mode_rows,
    COALESCE(c.duplicate_call_ids, 0) AS duplicate_call_ids,
    COALESCE(k.duplicate_cost_call_ids, 0) AS duplicate_cost_call_ids,
    o.run_row_count,
    o.browser_row_count,
    o.sync_status,
    o.is_verified,
    IFF(
        COALESCE(q.incomplete_step_rows, 0) = 0
        AND COALESCE(q.invalid_outcome_rows, 0) = 0
        AND COALESCE(q.invalid_guidance_mode_rows, 0) = 0
        AND COALESCE(c.duplicate_call_ids, 0) = 0
        AND COALESCE(k.duplicate_cost_call_ids, 0) = 0
        AND o.run_row_count = 1
        AND o.browser_row_count = 1,
        'clean',
        'attention_required'
    ) AS reconciliation_status
FROM V_SESSION_OVERVIEW AS o
LEFT JOIN step_quality AS q ON q.run_id = o.run_id
LEFT JOIN duplicate_calls AS c ON c.run_id = o.run_id
LEFT JOIN duplicate_costs AS k ON k.run_id = o.run_id;
