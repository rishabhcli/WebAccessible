from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session


APP_SCHEMA = '"WEBACCESSIBLE"."APP"'


st.set_page_config(
    page_title="WebAccessible Caregiver",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root {
        --wa-ink: #18211f;
        --wa-muted: #5d6965;
        --wa-line: #d8dfdc;
        --wa-panel: #f5f7f6;
        --wa-teal: #167d72;
        --wa-coral: #c95f45;
        --wa-gold: #9b741d;
      }
      html, body, [class*="css"] { letter-spacing: 0 !important; }
      .block-container { max-width: 1480px; padding-top: 1.75rem; }
      h1, h2, h3 { color: var(--wa-ink); letter-spacing: 0 !important; }
      [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid var(--wa-line);
        border-radius: 6px;
        padding: 0.8rem 1rem;
      }
      [data-testid="stMetricLabel"] { color: var(--wa-muted); }
      [data-testid="stSidebar"] { border-right: 1px solid var(--wa-line); }
      .wa-status {
        display: inline-block;
        border: 1px solid var(--wa-line);
        border-radius: 4px;
        color: var(--wa-ink);
        background: var(--wa-panel);
        font-size: 0.82rem;
        font-weight: 650;
        padding: 0.22rem 0.48rem;
      }
      .wa-rule { border-top: 1px solid var(--wa-line); margin: 1rem 0; }
      div[data-baseweb="tab-list"] { gap: 1rem; }
      div[data-baseweb="tab"] { letter-spacing: 0 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=30, show_spinner=False)
def query_frame(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(sql, params=list(params)).to_pandas()


def load_runs() -> pd.DataFrame:
    return query_frame(
        f"""
        SELECT
            user_id,
            task_id,
            task_name,
            run_id,
            session_id,
            run_no,
            run_kind,
            mode,
            started_at,
            ended_at,
            terminal_outcome,
            terminal_provenance,
            verified_amount,
            verified_currency,
            skill_id,
            skill_revision,
            everos_case_id,
            everos_skill_id,
            everos_episode_id,
            browserbase_session_id,
            browserbase_status,
            browserbase_region,
            build_commit,
            model_call_count,
            actual_model_tokens,
            cost_status,
            actual_cost_usd,
            cold_baseline_usd,
            cost_reduction_ratio
        FROM {APP_SCHEMA}.V_COLD_WARM_COST_CURVE
        ORDER BY started_at DESC, run_id
        """
    )


def load_timeline(run_id: str) -> pd.DataFrame:
    return query_frame(
        f"""
        SELECT
            occurred_at,
            step_no,
            action,
            guidance_mode,
            outcome,
            replayed_from_memory,
            trusted_user_action,
            selector_tier,
            selector_result,
            verification_predicate,
            verification_result,
            model_used,
            input_tokens,
            output_tokens,
            latency_ms,
            event_id,
            step_id
        FROM {APP_SCHEMA}.V_SESSION_TIMELINE
        WHERE run_id = ?
        ORDER BY step_no, occurred_at
        """,
        (run_id,),
    )


def load_provider_status(run_id: str) -> pd.DataFrame:
    return query_frame(
        f"""
        SELECT *
        FROM {APP_SCHEMA}.V_PROVIDER_SYNC_STATUS
        WHERE run_id = ?
        """,
        (run_id,),
    )


def load_selector_evidence(run_id: str) -> pd.DataFrame:
    return query_frame(
        f"""
        SELECT
            observed_at,
            step_id,
            attempt_no,
            selector_tier,
            resolution_result,
            matched_candidate_count,
            verification_predicate,
            verification_result,
            trusted_user_action,
            replayed_from_memory,
            evidence_status,
            model_call_id,
            selector_attempt_id
        FROM {APP_SCHEMA}.V_SELECTOR_REPLAY_EVIDENCE
        WHERE run_id = ?
        ORDER BY observed_at, step_id, attempt_no
        """,
        (run_id,),
    )


def load_cost_lineage(run_id: str) -> pd.DataFrame:
    return query_frame(
        f"""
        SELECT
            requested_at,
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
            amount_usd,
            calculation_status,
            is_cost_verified,
            rate_source_reference
        FROM {APP_SCHEMA}.V_MODEL_COST_LINEAGE
        WHERE run_id = ?
        ORDER BY requested_at, call_id
        """,
        (run_id,),
    )


def load_skill_lineage(run_id: str) -> pd.DataFrame:
    return query_frame(
        f"""
        SELECT
            skill_revision_link_id,
            skill_key,
            revision,
            everos_skill_id,
            everos_case_id,
            parent_revision,
            task_outcome,
            repair_reason,
            provider_status,
            indexing_status,
            is_current,
            written_at,
            retrieved_at,
            source_step_id
        FROM {APP_SCHEMA}.V_SKILL_LINEAGE
        WHERE source_run_id = ?
        ORDER BY revision DESC, written_at DESC
        """,
        (run_id,),
    )


def load_escalations(run_id: str) -> pd.DataFrame:
    return query_frame(
        f"""
        SELECT
            created_at,
            reason,
            status,
            delivery_channel,
            delivery_attempt_count,
            delivery_attempted_at,
            delivery_receipt_at,
            caregiver_response_status,
            caregiver_response_at,
            escalation_id
        FROM {APP_SCHEMA}.V_ESCALATION_OVERVIEW
        WHERE run_id = ?
        ORDER BY created_at DESC
        """,
        (run_id,),
    )


def money(value: Any, currency: str = "USD") -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    numeric = Decimal(str(value))
    if currency == "USD":
        return f"${numeric:,.4f}"
    return f"{numeric:,.4f} {currency}"


def short_time(value: Any) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y %I:%M %p")
    return str(value)


def status_label(value: Any) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    return str(value).replace("_", " ").strip().lower()


st.title("WebAccessible")
st.caption("Caregiver session record")

try:
    runs = load_runs()
except Exception:
    st.error("Verified data is unavailable")
    st.stop()

if runs.empty:
    st.subheader("No verified data")
    st.write(
        "Completed live sessions appear after Browserbase, EverOS, and Snowflake evidence is synchronized."
    )
    st.stop()

users = sorted(runs["USER_ID"].dropna().astype(str).unique().tolist())
selected_user = st.sidebar.selectbox("Supported adult", users)

user_runs = runs[runs["USER_ID"].astype(str) == selected_user].copy()
task_names = sorted(user_runs["TASK_NAME"].dropna().astype(str).unique().tolist())
selected_task = st.sidebar.selectbox("Routine", ["All routines", *task_names])
if selected_task != "All routines":
    user_runs = user_runs[user_runs["TASK_NAME"].astype(str) == selected_task].copy()

if user_runs.empty:
    st.subheader("No verified data")
    st.stop()

run_labels: dict[str, str] = {}
for row in user_runs.itertuples(index=False):
    run_id = str(row.RUN_ID)
    run_labels[run_id] = (
        f"{row.TASK_NAME} - run {row.RUN_NO} - "
        f"{short_time(row.STARTED_AT)}"
    )

run_options = user_runs["RUN_ID"].astype(str).tolist()
selected_run = st.sidebar.selectbox(
    "Session",
    run_options,
    format_func=lambda run_id: run_labels.get(run_id, run_id),
)
selected = user_runs[user_runs["RUN_ID"].astype(str) == selected_run].iloc[0]

all_user_runs = runs[runs["USER_ID"].astype(str) == selected_user]
completed_count = int((all_user_runs["TERMINAL_OUTCOME"] == "completed").sum())
warm_count = int((all_user_runs["RUN_KIND"] == "warm").sum())
known_costs = all_user_runs["ACTUAL_COST_USD"].dropna()
total_cost = known_costs.sum() if not known_costs.empty else None

metric_columns = st.columns(4)
metric_columns[0].metric("Verified sessions", len(all_user_runs))
metric_columns[1].metric("Completed", completed_count)
metric_columns[2].metric("Warm replays", warm_count)
metric_columns[3].metric("Actual inference cost", money(total_cost))

st.markdown('<div class="wa-rule"></div>', unsafe_allow_html=True)

overview_tab, session_tab, replay_tab, memory_tab, provider_tab = st.tabs(
    ["Overview", "Session", "Replay evidence", "Memory and escalation", "Provider status"]
)

with overview_tab:
    st.subheader("Verified run history")
    history = user_runs[
        [
            "STARTED_AT",
            "TASK_NAME",
            "RUN_NO",
            "RUN_KIND",
            "TERMINAL_OUTCOME",
            "MODEL_CALL_COUNT",
            "ACTUAL_MODEL_TOKENS",
            "COST_STATUS",
            "ACTUAL_COST_USD",
            "RUN_ID",
        ]
    ].sort_values(["TASK_NAME", "RUN_NO"])
    st.dataframe(
        history,
        width="stretch",
        hide_index=True,
        column_config={
            "STARTED_AT": st.column_config.DatetimeColumn("Started", format="MMM D, YYYY h:mm a"),
            "TASK_NAME": "Routine",
            "RUN_NO": "Run",
            "RUN_KIND": "Kind",
            "TERMINAL_OUTCOME": "Outcome",
            "MODEL_CALL_COUNT": "Calls",
            "ACTUAL_MODEL_TOKENS": "Tokens",
            "COST_STATUS": "Cost status",
            "ACTUAL_COST_USD": st.column_config.NumberColumn("Actual USD", format="$%.4f"),
            "RUN_ID": "Run ID",
        },
    )

    st.subheader("Cold and warm cost")
    chart_data = user_runs[user_runs["ACTUAL_COST_USD"].notna()].copy()
    chart_data = chart_data.sort_values(["TASK_NAME", "RUN_NO"])
    if chart_data.empty:
        st.info("No verified cost data")
    else:
        chart_data["RUN_LABEL"] = chart_data.apply(
            lambda row: f"{row['TASK_NAME']} #{int(row['RUN_NO'])}", axis=1
        )
        st.bar_chart(
            chart_data,
            x="RUN_LABEL",
            y="ACTUAL_COST_USD",
            color="RUN_KIND",
            stack=False,
            height=340,
        )
        cost_table = chart_data[
            [
                "TASK_NAME",
                "RUN_NO",
                "RUN_KIND",
                "ACTUAL_COST_USD",
                "COLD_BASELINE_USD",
                "COST_REDUCTION_RATIO",
                "MODEL_CALL_COUNT",
                "ACTUAL_MODEL_TOKENS",
            ]
        ].copy()
        cost_table["COST_REDUCTION_PERCENT"] = (
            cost_table["COST_REDUCTION_RATIO"] * 100
        )
        cost_table = cost_table.drop(columns=["COST_REDUCTION_RATIO"])
        st.dataframe(
            cost_table,
            width="stretch",
            hide_index=True,
            column_config={
                "TASK_NAME": "Routine",
                "RUN_NO": "Run",
                "RUN_KIND": "Kind",
                "ACTUAL_COST_USD": st.column_config.NumberColumn("Actual USD", format="$%.4f"),
                "COLD_BASELINE_USD": st.column_config.NumberColumn("Cold baseline", format="$%.4f"),
                "COST_REDUCTION_PERCENT": st.column_config.NumberColumn("Reduction", format="%.1f%%"),
                "MODEL_CALL_COUNT": "Calls",
                "ACTUAL_MODEL_TOKENS": "Tokens",
            },
        )

with session_tab:
    st.subheader(f"{selected['TASK_NAME']} - run {selected['RUN_NO']}")
    st.markdown(
        f'<span class="wa-status">{status_label(selected["TERMINAL_OUTCOME"])}</span>',
        unsafe_allow_html=True,
    )
    detail_columns = st.columns(4)
    detail_columns[0].metric("Started", short_time(selected["STARTED_AT"]))
    detail_columns[1].metric("Run mode", status_label(selected["RUN_KIND"]))
    detail_columns[2].metric("Model calls", int(selected["MODEL_CALL_COUNT"]))
    detail_columns[3].metric("Actual cost", money(selected["ACTUAL_COST_USD"]))

    if selected["VERIFIED_AMOUNT"] is not None and not pd.isna(selected["VERIFIED_AMOUNT"]):
        currency_value = selected["VERIFIED_CURRENCY"]
        currency = (
            "USD"
            if currency_value is None or pd.isna(currency_value)
            else str(currency_value)
        )
        st.metric("Verified outcome amount", money(selected["VERIFIED_AMOUNT"], currency))

    timeline = load_timeline(selected_run)
    st.subheader("Timeline")
    if timeline.empty:
        st.info("No verified step data")
    else:
        st.dataframe(
            timeline,
            width="stretch",
            hide_index=True,
            column_config={
                "OCCURRED_AT": st.column_config.DatetimeColumn("Time", format="h:mm:ss a"),
                "STEP_NO": "Step",
                "ACTION": "Action",
                "GUIDANCE_MODE": "Guidance",
                "OUTCOME": "Outcome",
                "REPLAYED_FROM_MEMORY": "Replay",
                "TRUSTED_USER_ACTION": "User action",
                "SELECTOR_TIER": "Selector",
                "SELECTOR_RESULT": "Resolution",
                "VERIFICATION_PREDICATE": "Predicate",
                "VERIFICATION_RESULT": "Verification",
                "MODEL_USED": "Model",
                "INPUT_TOKENS": "Input tokens",
                "OUTPUT_TOKENS": "Output tokens",
                "LATENCY_MS": "Latency ms",
                "EVENT_ID": "Event ID",
                "STEP_ID": "Step ID",
            },
        )

    st.subheader("Outcome evidence")
    outcome_rows = pd.DataFrame(
        [
            {
                "Outcome": selected["TERMINAL_OUTCOME"],
                "Provenance": selected["TERMINAL_PROVENANCE"],
                "EverOS episode": selected["EVEROS_EPISODE_ID"],
                "EverOS skill": selected["EVEROS_SKILL_ID"],
                "Build": selected["BUILD_COMMIT"],
                "Run ID": selected["RUN_ID"],
                "Session ID": selected["SESSION_ID"],
            }
        ]
    )
    st.dataframe(outcome_rows, width="stretch", hide_index=True)

with replay_tab:
    st.subheader("Selector and verification evidence")
    selector_evidence = load_selector_evidence(selected_run)
    if selector_evidence.empty:
        st.info("No verified selector evidence")
    else:
        st.dataframe(
            selector_evidence,
            width="stretch",
            hide_index=True,
            column_config={
                "OBSERVED_AT": st.column_config.DatetimeColumn("Observed", format="h:mm:ss a"),
                "STEP_ID": "Step ID",
                "ATTEMPT_NO": "Attempt",
                "SELECTOR_TIER": "Selector tier",
                "RESOLUTION_RESULT": "Resolution",
                "MATCHED_CANDIDATE_COUNT": "Matches",
                "VERIFICATION_PREDICATE": "Predicate",
                "VERIFICATION_RESULT": "Verification",
                "TRUSTED_USER_ACTION": "User action",
                "REPLAYED_FROM_MEMORY": "Replay",
                "EVIDENCE_STATUS": "Evidence",
                "MODEL_CALL_ID": "Model call ID",
                "SELECTOR_ATTEMPT_ID": "Attempt ID",
            },
        )

    st.subheader("Model and rate lineage")
    cost_lineage = load_cost_lineage(selected_run)
    if cost_lineage.empty:
        if selected["RUN_KIND"] == "warm" and int(selected["MODEL_CALL_COUNT"]) == 0:
            st.success("Verified warm replay: zero model calls and zero inference cost")
        else:
            st.info("No verified model call data")
    else:
        st.dataframe(
            cost_lineage,
            width="stretch",
            hide_index=True,
            column_config={
                "REQUESTED_AT": st.column_config.DatetimeColumn("Requested", format="h:mm:ss a"),
                "CALL_ID": "Call ID",
                "STEP_ID": "Step ID",
                "GUIDANCE_MODE": "Guidance",
                "PROVIDER": "Provider",
                "MODEL": "Model",
                "MODEL_VERSION": "Version",
                "ACTUAL_INPUT_TOKENS": "Input",
                "ACTUAL_CACHED_INPUT_TOKENS": "Cached",
                "ACTUAL_REASONING_TOKENS": "Reasoning",
                "ACTUAL_OUTPUT_TOKENS": "Output",
                "USAGE_STATUS": "Usage",
                "CALL_STATUS": "Call status",
                "RATE_CARD_VERSION": "Rate card",
                "TOKEN_CLASSES": "Token classes",
                "AMOUNT_USD": st.column_config.NumberColumn("Actual USD", format="$%.6f"),
                "CALCULATION_STATUS": "Calculation",
                "IS_COST_VERIFIED": "Verified",
                "RATE_SOURCE_REFERENCE": "Rate source",
            },
        )

with memory_tab:
    st.subheader("EverOS skill lineage")
    skills = load_skill_lineage(selected_run)
    if skills.empty:
        st.info("No verified skill data")
    else:
        st.dataframe(
            skills,
            width="stretch",
            hide_index=True,
            column_config={
                "SKILL_REVISION_LINK_ID": "Revision link ID",
                "SKILL_KEY": "Skill key",
                "REVISION": "Revision",
                "EVEROS_SKILL_ID": "EverOS skill ID",
                "EVEROS_CASE_ID": "EverOS case ID",
                "PARENT_REVISION": "Parent",
                "TASK_OUTCOME": "Outcome",
                "REPAIR_REASON": "Repair",
                "PROVIDER_STATUS": "Provider",
                "INDEXING_STATUS": "Indexing",
                "IS_CURRENT": "Current",
                "WRITTEN_AT": st.column_config.DatetimeColumn("Written", format="MMM D, YYYY h:mm a"),
                "RETRIEVED_AT": st.column_config.DatetimeColumn("Retrieved", format="MMM D, YYYY h:mm a"),
                "SOURCE_STEP_ID": "Source step",
            },
        )

    st.subheader("Escalations")
    escalations = load_escalations(selected_run)
    if escalations.empty:
        st.info("No escalations")
    else:
        st.dataframe(
            escalations,
            width="stretch",
            hide_index=True,
            column_config={
                "CREATED_AT": st.column_config.DatetimeColumn("Created", format="MMM D, YYYY h:mm a"),
                "REASON": "Reason",
                "STATUS": "Status",
                "DELIVERY_CHANNEL": "Channel",
                "DELIVERY_ATTEMPT_COUNT": "Attempts",
                "DELIVERY_ATTEMPTED_AT": st.column_config.DatetimeColumn("Attempted", format="h:mm a"),
                "DELIVERY_RECEIPT_AT": st.column_config.DatetimeColumn("Receipt", format="h:mm a"),
                "CAREGIVER_RESPONSE_STATUS": "Response",
                "CAREGIVER_RESPONSE_AT": st.column_config.DatetimeColumn("Responded", format="h:mm a"),
                "ESCALATION_ID": "Escalation ID",
            },
        )

with provider_tab:
    st.subheader("Provider and synchronization state")
    provider = load_provider_status(selected_run)
    if provider.empty:
        st.info("No verified provider data")
    else:
        provider_display = provider.copy()
        provider_display["BROWSERBASE_SESSION"] = provider_display[
            "BROWSERBASE_SESSION_ID"
        ].apply(
            lambda value: (
                f"https://www.browserbase.com/sessions/{value}"
                if value is not None and not pd.isna(value)
                else None
            )
        )
        st.dataframe(
            provider_display[
                [
                    "BROWSERBASE_STATUS",
                    "TELEMETRY_STATUS",
                    "EVEROS_PROVIDER_STATUS",
                    "EVEROS_INDEXING_STATUS",
                    "CDP_ATTACHED_AT",
                    "LIVE_VIEW_READY_AT",
                    "FIRST_TRUSTED_USER_ACTION_AT",
                    "TERMINATED_AT",
                    "AGENT_SURFACE_USED",
                    "STEP_ROW_COUNT",
                    "DISTINCT_EVENT_COUNT",
                    "INGESTION_PENDING_COUNT",
                    "INGESTION_FAILED_COUNT",
                    "MODEL_CALL_COUNT",
                    "MODEL_CALL_FAILURE_COUNT",
                    "IS_VERIFIED",
                    "BROWSERBASE_SESSION",
                    "EVEROS_SKILL_ID",
                ]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "BROWSERBASE_STATUS": "Browserbase",
                "TELEMETRY_STATUS": "Telemetry",
                "EVEROS_PROVIDER_STATUS": "EverOS",
                "EVEROS_INDEXING_STATUS": "Indexing",
                "CDP_ATTACHED_AT": st.column_config.DatetimeColumn("CDP attached", format="h:mm:ss a"),
                "LIVE_VIEW_READY_AT": st.column_config.DatetimeColumn("Live View ready", format="h:mm:ss a"),
                "FIRST_TRUSTED_USER_ACTION_AT": st.column_config.DatetimeColumn("First user action", format="h:mm:ss a"),
                "TERMINATED_AT": st.column_config.DatetimeColumn("Terminated", format="h:mm:ss a"),
                "AGENT_SURFACE_USED": "Agent used",
                "STEP_ROW_COUNT": "Step rows",
                "DISTINCT_EVENT_COUNT": "Events",
                "INGESTION_PENDING_COUNT": "Pending",
                "INGESTION_FAILED_COUNT": "Failed",
                "MODEL_CALL_COUNT": "Calls",
                "MODEL_CALL_FAILURE_COUNT": "Call failures",
                "IS_VERIFIED": "Verified",
                "BROWSERBASE_SESSION": st.column_config.LinkColumn(
                    "Browserbase session", display_text="Open session"
                ),
                "EVEROS_SKILL_ID": "EverOS skill ID",
            },
        )
