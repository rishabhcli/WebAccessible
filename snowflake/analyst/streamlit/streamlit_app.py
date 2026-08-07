"""WebAccessible caregiver questions.

A Streamlit in Snowflake application that answers plain-English caregiver questions over
verified WebAccessible data using Cortex Analyst and the semantic view
WEBACCESSIBLE.ANALYST.CAREGIVER_REPORTING.

This application is separate from the live WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER
Streamlit entity. It reads only the WEBACCESSIBLE.ANALYST projection views and never writes.

Boundaries this file enforces, not just documents:

- Every answer is scoped to one selected user_id. Generated SQL that does not carry that
  scope is refused rather than executed.
- Generated SQL must be a single read-only statement.
- Every answer carries run/session identifiers and timestamps from an application-owned
  evidence query, so citation never depends on the model behaving.
- Empty or incomplete scopes render the exact words "No verified data".
- Cost totals are reported only from rate-card-backed verified columns, and an incomplete
  total is always labelled with the number of unpriced calls.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import _snowflake
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

ANALYST_SCHEMA = '"WEBACCESSIBLE"."ANALYST"'
SEMANTIC_VIEW = "WEBACCESSIBLE.ANALYST.CAREGIVER_REPORTING"
API_ENDPOINT = "/api/v2/cortex/analyst/message"
API_TIMEOUT_MS = 50_000

NO_VERIFIED_DATA = "No verified data"

WINDOWS: dict[str, int | None] = {
    "This week (last 7 days)": 7,
    "Last 14 days": 14,
    "Last 30 days": 30,
    "All verified history": None,
}

SUGGESTED_QUESTIONS = (
    "How did she do this week?",
    "Which routines did she finish, and which needed my help?",
    "How much of the work came from memory instead of the model?",
    "What did the sessions cost this week?",
    "Is the record complete for every session, or is a provider still behind?",
)

# Opaque product identifiers only. Anything else is refused before it reaches a prompt.
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:@\-]{1,128}$")

# Generated SQL must be a single read-only statement.
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|create|drop|alter|truncate|grant|revoke|call|execute"
    r"|copy|put|remove|unload|use|begin|commit|rollback|set|unset|describe|show)\b",
    re.IGNORECASE,
)

RUN_ID_COLUMNS = {
    "RUN_ID",
    "SESSION_ID",
    "EVENT_RUN_ID",
    "EVENT_SESSION_ID",
    "CALL_RUN_ID",
    "CALL_SESSION_ID",
    "ATTEMPT_RUN_ID",
    "ATTEMPT_SESSION_ID",
    "SYNC_RUN_ID",
    "SYNC_SESSION_ID",
    "ESCALATION_RUN_ID",
    "ESCALATION_SESSION_ID",
}


st.set_page_config(
    page_title="WebAccessible caregiver questions",
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
      }
      html, body, [class*="css"] { letter-spacing: 0 !important; }
      .block-container { max-width: 1180px; padding-top: 1.75rem; }
      h1, h2, h3 { color: var(--wa-ink); letter-spacing: 0 !important; }
      [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid var(--wa-line);
        border-radius: 6px;
        padding: 0.8rem 1rem;
      }
      [data-testid="stMetricLabel"] { color: var(--wa-muted); }
      [data-testid="stSidebar"] { border-right: 1px solid var(--wa-line); }
      .wa-scope {
        border: 1px solid var(--wa-line);
        border-left: 3px solid var(--wa-teal);
        background: var(--wa-panel);
        border-radius: 4px;
        color: var(--wa-ink);
        font-size: 0.86rem;
        padding: 0.6rem 0.75rem;
      }
      .wa-rule { border-top: 1px solid var(--wa-line); margin: 1rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Application-owned queries. Parameterized, read-only, never model generated.
# ---------------------------------------------------------------------------


def run_sql(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(sql, params=list(params)).to_pandas()


@st.cache_data(ttl=30, show_spinner=False)
def load_supported_adults() -> pd.DataFrame:
    return run_sql(
        f"""
        SELECT
            user_id,
            COUNT(*) AS verified_session_count,
            MIN(started_at) AS first_session_at,
            MAX(started_at) AS last_session_at
        FROM {ANALYST_SCHEMA}.V_CAREGIVER_SESSION
        GROUP BY user_id
        ORDER BY MAX(started_at) DESC
        """
    )


@st.cache_data(ttl=30, show_spinner=False)
def load_session_evidence(user_id: str, cutoff: str | None) -> pd.DataFrame:
    """Run and session identifiers with timestamps for the exact answered scope."""
    if cutoff is None:
        return run_sql(
            f"""
            SELECT
                run_id,
                session_id,
                task_name,
                run_no,
                run_kind,
                terminal_outcome,
                started_at,
                ended_at,
                cost_status,
                actual_cost_usd,
                model_call_count,
                actual_model_tokens,
                everos_skill_id,
                browserbase_session_id,
                build_commit
            FROM {ANALYST_SCHEMA}.V_CAREGIVER_SESSION
            WHERE user_id = ?
            ORDER BY started_at DESC, run_id
            """,
            (user_id,),
        )
    return run_sql(
        f"""
        SELECT
            run_id,
            session_id,
            task_name,
            run_no,
            run_kind,
            terminal_outcome,
            started_at,
            ended_at,
            cost_status,
            actual_cost_usd,
            model_call_count,
            actual_model_tokens,
            everos_skill_id,
            browserbase_session_id,
            build_commit
        FROM {ANALYST_SCHEMA}.V_CAREGIVER_SESSION
        WHERE user_id = ?
          AND started_at >= TRY_TO_TIMESTAMP_NTZ(?)
        ORDER BY started_at DESC, run_id
        """,
        (user_id, cutoff),
    )


@st.cache_data(ttl=30, show_spinner=False)
def load_cost_completeness(user_id: str, cutoff: str | None) -> pd.DataFrame:
    """Whether a cost total for this scope can be complete at all."""
    predicate = "s.user_id = ?" if cutoff is None else (
        "s.user_id = ? AND s.started_at >= TRY_TO_TIMESTAMP_NTZ(?)"
    )
    params: tuple[Any, ...] = (user_id,) if cutoff is None else (user_id, cutoff)
    return run_sql(
        f"""
        WITH scoped AS (
            SELECT s.run_id, s.cost_status, s.actual_cost_usd
            FROM {ANALYST_SCHEMA}.V_CAREGIVER_SESSION AS s
            WHERE {predicate}
        )
        SELECT
            COUNT(*) AS verified_session_count,
            COUNT_IF(cost_status = 'unavailable') AS cost_unavailable_session_count,
            SUM(actual_cost_usd) AS verified_cost_usd,
            (
                SELECT COUNT_IF(NOT m.is_cost_verified)
                FROM {ANALYST_SCHEMA}.V_CAREGIVER_MODEL_USAGE AS m
                WHERE m.run_id IN (SELECT run_id FROM scoped)
            ) AS unpriced_model_call_count,
            (
                SELECT COUNT(*)
                FROM {ANALYST_SCHEMA}.V_CAREGIVER_MODEL_USAGE AS m
                WHERE m.run_id IN (SELECT run_id FROM scoped)
            ) AS model_call_count
        FROM scoped
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Cortex Analyst
# ---------------------------------------------------------------------------


def call_analyst(messages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """Call the Cortex Analyst REST API over the semantic view."""
    request_body = {
        "messages": messages,
        "semantic_view": SEMANTIC_VIEW,
        # Streamlit in Snowflake does not support streaming responses.
        "stream": False,
    }
    try:
        response = _snowflake.send_snow_api_request(
            "POST",
            API_ENDPOINT,
            {},
            {},
            request_body,
            None,
            API_TIMEOUT_MS,
        )
    except Exception as exc:  # noqa: BLE001 - surface any transport failure verbatim
        return None, f"Cortex Analyst request failed: {exc}"

    try:
        parsed = json.loads(response["content"])
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"Cortex Analyst returned an unreadable response: {exc}"

    if response.get("status", 500) >= 400:
        request_id = parsed.get("request_id", "unavailable")
        error_code = parsed.get("error_code", "unavailable")
        message = parsed.get("message", "no message")
        return parsed, (
            f"Cortex Analyst error {response.get('status')} "
            f"(request {request_id}, code {error_code}): {message}"
        )
    return parsed, None


def scoped_question(question: str, user_id: str, cutoff: str | None) -> str:
    """Attach the machine-selected scope and the citation requirement to the question."""
    lines = [
        question.strip(),
        "",
        f"Scope: sessions.user_id = '{user_id}'.",
    ]
    if cutoff is not None:
        lines.append(
            f"Restrict results to sessions.session_started_at >= "
            f"TO_TIMESTAMP_NTZ('{cutoff}')."
        )
    lines.append(
        "Include sessions.run_id, sessions.session_id and sessions.session_started_at "
        "in the selected dimensions."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Guardrails on generated SQL
# ---------------------------------------------------------------------------


def strip_sql_comments(sql: str) -> str:
    without_line_comments = "\n".join(line.split("--", 1)[0] for line in sql.split("\n"))
    return re.sub(r"/\*.*?\*/", " ", without_line_comments, flags=re.DOTALL)


def read_only_failure(sql: str) -> str | None:
    """Return a reason the statement must not be executed, or None when it is safe."""
    body = strip_sql_comments(sql).strip().rstrip(";").strip()
    if not body:
        return "the generated statement is empty"
    if ";" in body:
        return "the generated statement contains more than one SQL statement"
    upper = body.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return "the generated statement does not begin with SELECT or WITH"
    forbidden = FORBIDDEN_SQL.search(body)
    if forbidden:
        return f"the generated statement contains the non-read-only keyword {forbidden.group(0)!r}"
    return None


def scope_enforced(sql: str, user_id: str) -> bool:
    """True when the generated SQL actually filters on the selected supported adult."""
    return f"'{user_id}'" in sql


def executable_sql(sql: str) -> str:
    return strip_sql_comments(sql).strip().rstrip(";").strip()


def has_citation_columns(frame: pd.DataFrame) -> bool:
    columns = {str(column).upper() for column in frame.columns}
    has_identifier = bool(columns & RUN_ID_COLUMNS)
    has_timestamp = any(
        pd.api.types.is_datetime64_any_dtype(frame[column]) for column in frame.columns
    )
    return has_identifier and has_timestamp


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("WebAccessible caregiver questions")
st.caption(
    "Cortex Analyst over the verified WebAccessible record. Verified sessions only; "
    "nothing here is estimated or illustrative."
)

try:
    adults = load_supported_adults()
except Exception:
    st.error("Verified data is unavailable")
    st.caption(
        "The Analyst reporting views could not be read. Confirm "
        "snowflake/analyst/migrations have been applied and that this application's role "
        "holds SELECT on WEBACCESSIBLE.ANALYST."
    )
    st.stop()

if adults.empty:
    st.subheader(NO_VERIFIED_DATA)
    st.write(
        "Sessions appear here after a real run is synchronized and every Browserbase, "
        "EverOS, and Snowflake verification predicate passes."
    )
    st.stop()

adult_options = adults["USER_ID"].dropna().astype(str).tolist()
selected_user = st.sidebar.selectbox("Supported adult", adult_options)
selected_window = st.sidebar.radio("Reporting window", list(WINDOWS.keys()), index=0)
window_days = WINDOWS[selected_window]

st.sidebar.markdown('<div class="wa-rule"></div>', unsafe_allow_html=True)
st.sidebar.markdown(
    "**Names are not stored in Snowflake.** Participant names live only in EverOS, so a "
    "question that names a person is scoped by the `user_id` selected above rather than by "
    "matching the name against data."
)

if not SAFE_IDENTIFIER.match(selected_user):
    st.subheader(NO_VERIFIED_DATA)
    st.error(
        "The selected user_id is not a plain product identifier, so it will not be placed "
        "into a Cortex Analyst request."
    )
    st.stop()

cutoff: str | None = None
if window_days is not None:
    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).replace(tzinfo=None).isoformat(
        sep=" ", timespec="seconds"
    )

try:
    evidence = load_session_evidence(selected_user, cutoff)
    completeness = load_cost_completeness(selected_user, cutoff)
except Exception:
    st.error("Verified data is unavailable")
    st.stop()

scope_note = (
    f"Answers are scoped to <code>user_id = {selected_user}</code> over "
    f"<strong>{selected_window.lower()}</strong>"
)
if cutoff is not None:
    scope_note += f", meaning sessions started at or after <code>{cutoff} UTC</code>"
st.markdown(f'<div class="wa-scope">{scope_note}.</div>', unsafe_allow_html=True)

if evidence.empty:
    st.subheader(NO_VERIFIED_DATA)
    st.write(
        f"There are no verified sessions for `{selected_user}` in {selected_window.lower()}. "
        "Widen the reporting window or wait for synchronization to complete. No metric is "
        "shown for an empty scope."
    )
    st.stop()

summary = completeness.iloc[0]
verified_sessions = int(summary["VERIFIED_SESSION_COUNT"] or 0)
cost_unavailable = int(summary["COST_UNAVAILABLE_SESSION_COUNT"] or 0)
unpriced_calls = int(summary["UNPRICED_MODEL_CALL_COUNT"] or 0)
model_calls = int(summary["MODEL_CALL_COUNT"] or 0)
verified_cost = summary["VERIFIED_COST_USD"]

metric_columns = st.columns(4)
metric_columns[0].metric("Verified sessions", verified_sessions)
metric_columns[1].metric(
    "Completed", int((evidence["TERMINAL_OUTCOME"] == "completed").sum())
)
metric_columns[2].metric("Model calls", model_calls)
metric_columns[3].metric(
    "Verified inference cost",
    NO_VERIFIED_DATA
    if verified_cost is None or pd.isna(verified_cost)
    else f"${float(verified_cost):,.6f}",
)

if cost_unavailable or unpriced_calls:
    st.warning(
        f"Cost for this scope is incomplete: {cost_unavailable} verified session(s) and "
        f"{unpriced_calls} model call(s) have no rate-card-backed price, so they contribute "
        "nothing to any total. No price is inferred for them."
    )

st.markdown('<div class="wa-rule"></div>', unsafe_allow_html=True)

if "history" not in st.session_state:
    st.session_state.history = []
if "pending" not in st.session_state:
    st.session_state.pending = None

st.subheader("Ask a question")
for row_start in range(0, len(SUGGESTED_QUESTIONS), 3):
    row = SUGGESTED_QUESTIONS[row_start : row_start + 3]
    for column, suggestion in zip(st.columns(3), row, strict=False):
        if column.button(suggestion, width="stretch"):
            st.session_state.pending = suggestion

typed = st.chat_input("For example: How did Margaret do this week?")
if typed:
    st.session_state.pending = typed


def render_answer(question: str) -> None:
    """Ask Cortex Analyst one question and render a fully cited answer."""
    st.markdown(f"**Question.** {question}")

    request = scoped_question(question, selected_user, cutoff)
    with st.spinner("Asking Cortex Analyst over verified data"):
        payload, error = call_analyst(
            [{"role": "user", "content": [{"type": "text", "text": request}]}]
        )

    if error is not None:
        st.subheader(NO_VERIFIED_DATA)
        st.error(error)
        return

    assert payload is not None
    request_id = payload.get("request_id", "unavailable")
    content = (payload.get("message") or {}).get("content") or []

    interpretation = [item.get("text", "") for item in content if item.get("type") == "text"]
    statements = [item.get("statement", "") for item in content if item.get("type") == "sql"]
    suggestions: list[str] = []
    for item in content:
        if item.get("type") == "suggestions":
            suggestions.extend(item.get("suggestions") or [])

    for warning in payload.get("warnings") or []:
        st.warning(f"Cortex Analyst warning: {warning.get('message', warning)}")

    if interpretation:
        st.markdown("\n\n".join(text for text in interpretation if text))

    if suggestions and not statements:
        st.subheader(NO_VERIFIED_DATA)
        st.write(
            "Cortex Analyst could not resolve the question to a single query over the "
            "verified model, so no metric is shown. It suggested:"
        )
        for suggestion in suggestions:
            st.markdown(f"- {suggestion}")
        render_evidence(request_id, None)
        return

    if not statements:
        st.subheader(NO_VERIFIED_DATA)
        st.write(
            "Cortex Analyst returned an explanation but no query, so nothing was read from "
            "the verified record."
        )
        render_evidence(request_id, None)
        return

    statement = statements[0]
    refusal = read_only_failure(statement)
    if refusal is not None:
        st.subheader(NO_VERIFIED_DATA)
        st.error(f"The generated query was not executed because {refusal}.")
        render_evidence(request_id, statement)
        return

    if not scope_enforced(statement, selected_user):
        st.subheader(NO_VERIFIED_DATA)
        st.error(
            f"The generated query was not executed because it does not filter on the "
            f"selected supported adult (user_id {selected_user}). Answers are never widened "
            "beyond the selected scope."
        )
        render_evidence(request_id, statement)
        return

    try:
        results = run_sql(executable_sql(statement))
    except Exception as exc:  # noqa: BLE001 - the failing statement is shown as evidence
        st.subheader(NO_VERIFIED_DATA)
        st.error(f"The generated query failed against the verified model: {exc}")
        render_evidence(request_id, statement)
        return

    if results.empty:
        st.subheader(NO_VERIFIED_DATA)
        st.write(
            "The query ran against the verified model and matched no rows. No substitute, "
            "example, or typical value is shown."
        )
        render_evidence(request_id, statement)
        return

    st.dataframe(results, width="stretch", hide_index=True)

    if not has_citation_columns(results):
        st.info(
            "This result is an aggregate without its own identifiers. The runs and "
            "timestamps it was computed from are listed under Evidence below."
        )

    lowered_columns = {str(column).lower() for column in results.columns}
    if any("cost" in column or "usd" in column for column in lowered_columns):
        if unpriced_calls or cost_unavailable:
            st.warning(
                f"This cost is incomplete for the scope: {unpriced_calls} model call(s) and "
                f"{cost_unavailable} session(s) carry no rate-card-backed price and were "
                "excluded rather than estimated."
            )
        else:
            st.caption(
                "Every model call in this scope is priced from a MODEL_COSTS row and a "
                "matching COST_RATE_CARDS row. No amount is inferred."
            )

    render_evidence(request_id, statement)


def render_evidence(request_id: str, statement: str | None) -> None:
    """Always-available citation: the runs, sessions, and timestamps behind the scope."""
    with st.expander("Evidence", expanded=False):
        st.markdown(
            f"**Scope.** `user_id = {selected_user}`, {selected_window.lower()}"
            + (f", sessions started at or after `{cutoff} UTC`" if cutoff else "")
        )
        st.markdown(f"**Semantic view.** `{SEMANTIC_VIEW}`")
        st.markdown(f"**Cortex Analyst request id.** `{request_id}`")

        st.markdown("**Verified runs and sessions in scope**")
        st.dataframe(
            evidence,
            width="stretch",
            hide_index=True,
            column_config={
                "RUN_ID": "Run ID",
                "SESSION_ID": "Session ID",
                "TASK_NAME": "Routine",
                "RUN_NO": "Run",
                "RUN_KIND": "Kind",
                "TERMINAL_OUTCOME": "Outcome",
                "STARTED_AT": st.column_config.DatetimeColumn(
                    "Started (UTC)", format="MMM D, YYYY HH:mm:ss"
                ),
                "ENDED_AT": st.column_config.DatetimeColumn(
                    "Ended (UTC)", format="MMM D, YYYY HH:mm:ss"
                ),
                "COST_STATUS": "Cost status",
                "ACTUAL_COST_USD": st.column_config.NumberColumn(
                    "Verified USD", format="$%.6f"
                ),
                "MODEL_CALL_COUNT": "Calls",
                "ACTUAL_MODEL_TOKENS": "Tokens",
                "EVEROS_SKILL_ID": "EverOS skill ID",
                "BROWSERBASE_SESSION_ID": "Browserbase session ID",
                "BUILD_COMMIT": "Build",
            },
        )

        if statement:
            st.markdown("**Generated SQL**")
            st.code(statement, language="sql")


if st.session_state.pending:
    question = str(st.session_state.pending)
    st.session_state.pending = None
    render_answer(question)
    st.session_state.history.insert(0, question)

if st.session_state.history:
    st.markdown('<div class="wa-rule"></div>', unsafe_allow_html=True)
    with st.expander("Earlier questions in this visit", expanded=False):
        for earlier in st.session_state.history:
            st.markdown(f"- {earlier}")
