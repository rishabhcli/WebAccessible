#!/usr/bin/env python3
"""Static validation for the WebAccessible caregiver reporting semantic model.

This never connects to Snowflake. It checks the semantic-view YAML specification against
the documented key vocabulary, cross-checks every ``expr`` against the columns actually
projected by ``migrations/011_analyst_reporting_views.sql``, and enforces the WebAccessible
privacy and cost-honesty boundaries.

Run:

    python3 snowflake/analyst/validate/validate_semantic_model.py \
        snowflake/analyst/semantic/caregiver_reporting.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Key vocabulary from the Snowflake YAML specification for semantic views.
TOP_LEVEL_KEYS = {
    "name",
    "description",
    "tables",
    "relationships",
    "variables",
    "metrics",
    "verified_queries",
    "custom_instructions",
    "module_custom_instructions",
    "max_staleness",
    "tags",
}
TABLE_KEYS = {
    "name",
    "description",
    "base_table",
    "primary_key",
    "unique_keys",
    "dimensions",
    "time_dimensions",
    "facts",
    "metrics",
    "filters",
    "tags",
}
BASE_TABLE_KEYS = {"database", "schema", "table", "definition"}
DIMENSION_KEYS = {
    "name",
    "synonyms",
    "description",
    "expr",
    "data_type",
    "cortex_search_service",
    "is_enum",
    "labels",
    "tags",
    "sample_values",
}
TIME_DIMENSION_KEYS = {"name", "synonyms", "description", "expr", "data_type", "sample_values"}
FACT_KEYS = {
    "name",
    "synonyms",
    "description",
    "access_modifier",
    "expr",
    "data_type",
    "labels",
    "tags",
}
METRIC_KEYS = {
    "name",
    "synonyms",
    "description",
    "access_modifier",
    "expr",
    "non_additive_dimensions",
    "using_relationships",
    "tags",
    "data_type",
}
RELATIONSHIP_KEYS = {
    "name",
    "left_table",
    "right_table",
    "relationship_columns",
    "type",
    "right_range",
}
VERIFIED_QUERY_KEYS = {
    "name",
    "question",
    "sql",
    "verified_at",
    "verified_by",
    "use_as_onboarding_question",
}
MODULE_INSTRUCTION_KEYS = {"sql_generation", "question_categorization"}

# The Analyst layer must never surface these, per docs/privacy-data-map.md and
# IMPLEMENTATION_PLAN.md 6.6. Matched against every expr and every base table column.
FORBIDDEN_COLUMNS = {
    "verification_predicate",
    "selector_fingerprint",
    "provider_response_id_hash",
    "provider_message_id_hash",
    "payload_hash",
    "caregiver_response_metadata",
    "url",
    "full_url",
    "page_url",
    "raw_dom",
    "dom_snapshot",
    "prompt",
    "prompt_text",
    "completion_text",
    "document_text",
    "phone",
    "phone_number",
    "account_number",
    "password",
    "api_key",
    "token",
    "cdp_url",
    "live_view_url",
}

# Raw cost columns that must never be exposed directly. Only the gated
# verified_cost_usd / actual_cost_usd projections may reach the semantic model.
FORBIDDEN_COST_COLUMNS = {
    "amount_usd",
    "amount_currency",
    "credits",
    "input_amount",
    "cached_input_amount",
    "reasoning_amount",
    "output_amount",
    "unit_price",
}

AGGREGATE_PATTERN = re.compile(
    r"\b(COUNT|SUM|AVG|MIN|MAX|MEDIAN|STDDEV|VARIANCE|APPROX_COUNT_DISTINCT|"
    r"PERCENTILE_CONT|ANY_VALUE|BOOLOR_AGG|BOOLAND_AGG|LISTAGG)\s*\(",
    re.IGNORECASE,
)
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
BARE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SQL_WORDS = {
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "distinct",
    "iff",
    "case",
    "when",
    "then",
    "else",
    "end",
    "coalesce",
    "cast",
    "as",
    "null",
    "and",
    "or",
    "not",
    "datediff",
    "dateadd",
    "current_timestamp",
    "second",
    "day",
}

ANALYST_DATABASE = "WEBACCESSIBLE"
ANALYST_SCHEMA = "ANALYST"


class Findings:
    """Collects errors so one run reports every problem instead of the first."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def check(self, condition: bool, message: str) -> bool:
        if not condition:
            self.errors.append(message)
        return condition

    def fail(self, message: str) -> None:
        self.errors.append(message)


def strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.split("\n"))


def split_top_level(text: str, separator: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    in_string = False
    for char in text:
        if char == "'":
            in_string = not in_string
        if not in_string:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == separator and depth == 0:
                parts.append("".join(current))
                current = []
                continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def projected_columns(select_list: str) -> set[str]:
    """Return the output column names of a SELECT list."""
    columns: set[str] = set()
    for item in split_top_level(select_list):
        flat = " ".join(item.split())
        alias_parts = split_top_level(flat, " ")
        alias = None
        for index in range(len(alias_parts) - 1, 0, -1):
            if alias_parts[index - 1].upper() == "AS":
                alias = alias_parts[index]
                break
        name = alias if alias else flat.rsplit(".", 1)[-1]
        if BARE_IDENTIFIER_PATTERN.match(name):
            columns.add(name.lower())
    return columns


def parse_view_columns(sql_path: Path, findings: Findings) -> dict[str, set[str]]:
    """Map each ANALYST view name to the set of column names it projects."""
    sql = strip_sql_comments(sql_path.read_text(encoding="utf-8"))
    views: dict[str, set[str]] = {}
    pattern = re.compile(
        r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
        r".*?\bAS\s*\bSELECT\b(?P<body>.*?)\bFROM\b",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql):
        name = match.group("name").upper()
        columns = projected_columns(match.group("body"))
        if not findings.check(bool(columns), f"{sql_path.name}: view {name} projects no columns"):
            continue
        views[name] = columns
    findings.check(bool(views), f"{sql_path.name}: no CREATE OR REPLACE VIEW statements found")
    return views


def expr_identifiers(expr: str) -> set[str]:
    return {
        token.lower()
        for token in IDENTIFIER_PATTERN.findall(expr)
        if token.lower() not in SQL_WORDS
    }


def check_unknown_keys(
    findings: Findings, where: str, mapping: dict[str, Any], allowed: set[str]
) -> None:
    for key in mapping:
        if key not in allowed:
            findings.fail(f"{where}: unsupported key {key!r}; allowed keys are {sorted(allowed)}")


def check_field(
    findings: Findings,
    table_name: str,
    kind: str,
    field: dict[str, Any],
    allowed_keys: set[str],
    columns: set[str],
    seen_names: dict[str, str],
) -> None:
    name = field.get("name")
    where = f"table {table_name} {kind} {name!r}"
    check_unknown_keys(findings, where, field, allowed_keys)

    if not findings.check(isinstance(name, str) and bool(name), f"{where}: missing name"):
        return
    assert isinstance(name, str)

    if name in seen_names:
        findings.fail(
            f"{where}: name {name!r} is already used by {seen_names[name]}; "
            "semantic expression names must be unique across the whole model"
        )
    else:
        seen_names[name] = where

    findings.check(
        isinstance(field.get("description"), str) and bool(field.get("description")),
        f"{where}: missing description; Cortex Analyst relies on it to pick the right column",
    )

    expr = field.get("expr")
    if not findings.check(isinstance(expr, str) and bool(expr), f"{where}: missing expr"):
        return
    assert isinstance(expr, str)

    lowered = name.lower()
    for forbidden in FORBIDDEN_COLUMNS | FORBIDDEN_COST_COLUMNS:
        if forbidden in expr_identifiers(expr) or lowered == forbidden:
            findings.fail(
                f"{where}: expr {expr!r} references excluded column {forbidden!r}; "
                "see migrations/011_analyst_reporting_views.sql for the allowlist policy"
            )

    if kind == "metric":
        findings.check(
            bool(AGGREGATE_PATTERN.search(expr)),
            f"{where}: a non-derived metric must use an aggregate function, got {expr!r}",
        )
        unknown = expr_identifiers(expr) - columns
        if unknown:
            findings.fail(
                f"{where}: expr {expr!r} references column(s) {sorted(unknown)} "
                f"not projected by the base view"
            )
        return

    findings.check(
        bool(BARE_IDENTIFIER_PATTERN.match(expr)),
        f"{where}: expr {expr!r} should be a plain column of the base view so the "
        "projection stays the single place redaction happens",
    )
    if BARE_IDENTIFIER_PATTERN.match(expr):
        findings.check(
            expr.lower() in columns,
            f"{where}: expr {expr!r} is not projected by the base view",
        )


def check_table(
    findings: Findings,
    table: dict[str, Any],
    views: dict[str, set[str]],
    seen_names: dict[str, str],
) -> str | None:
    name = table.get("name")
    where = f"table {name!r}"
    check_unknown_keys(findings, where, table, TABLE_KEYS)
    if not findings.check(isinstance(name, str) and bool(name), "a table is missing its name"):
        return None
    assert isinstance(name, str)

    findings.check(
        isinstance(table.get("description"), str) and bool(table.get("description")),
        f"{where}: missing description",
    )

    base_table = table.get("base_table")
    if not findings.check(isinstance(base_table, dict), f"{where}: missing base_table"):
        return name
    assert isinstance(base_table, dict)
    check_unknown_keys(findings, f"{where} base_table", base_table, BASE_TABLE_KEYS)

    findings.check(
        base_table.get("database") == ANALYST_DATABASE,
        f"{where}: base_table.database must be {ANALYST_DATABASE}, "
        f"got {base_table.get('database')!r}",
    )
    findings.check(
        base_table.get("schema") == ANALYST_SCHEMA,
        f"{where}: base_table.schema must be {ANALYST_SCHEMA} so the model reads only the "
        f"redacted projection layer, got {base_table.get('schema')!r}",
    )
    findings.check(
        "definition" not in base_table,
        f"{where}: base_table.definition is not allowed; every logical table must resolve to "
        "a reviewed view in the projection layer",
    )

    view_name = base_table.get("table")
    columns: set[str] = set()
    if findings.check(isinstance(view_name, str) and bool(view_name), f"{where}: missing table"):
        assert isinstance(view_name, str)
        upper = view_name.upper()
        findings.check(
            upper.startswith("V_CAREGIVER_"),
            f"{where}: base_table.table {view_name!r} is not a V_CAREGIVER_* projection view",
        )
        if findings.check(
            upper in views,
            f"{where}: base_table.table {view_name!r} is not created by "
            "migrations/011_analyst_reporting_views.sql",
        ):
            columns = views[upper]

    primary_key = table.get("primary_key")
    if primary_key is not None:
        if findings.check(isinstance(primary_key, dict), f"{where}: primary_key must be a mapping"):
            assert isinstance(primary_key, dict)
            key_columns = primary_key.get("columns")
            if findings.check(
                isinstance(key_columns, list) and bool(key_columns),
                f"{where}: primary_key.columns must be a non-empty list",
            ):
                assert isinstance(key_columns, list)
                for column in key_columns:
                    findings.check(
                        isinstance(column, str) and column.lower() in columns,
                        f"{where}: primary_key column {column!r} is not projected by the view",
                    )

    kinds = (
        ("dimension", "dimensions", DIMENSION_KEYS),
        ("time_dimension", "time_dimensions", TIME_DIMENSION_KEYS),
        ("fact", "facts", FACT_KEYS),
        ("metric", "metrics", METRIC_KEYS),
    )
    has_dimension_or_metric = False
    for kind, key, allowed in kinds:
        fields = table.get(key, [])
        if not fields:
            continue
        if not findings.check(isinstance(fields, list), f"{where}: {key} must be a list"):
            continue
        assert isinstance(fields, list)
        if kind in {"dimension", "time_dimension", "metric"}:
            has_dimension_or_metric = True
        for field in fields:
            if not findings.check(isinstance(field, dict), f"{where}: {key} entries must be maps"):
                continue
            assert isinstance(field, dict)
            check_field(findings, name, kind, field, allowed, columns, seen_names)

    findings.check(
        has_dimension_or_metric,
        f"{where}: a semantic view table must define at least one dimension or metric",
    )
    return name


def check_relationships(
    findings: Findings, relationships: Any, tables: dict[str, dict[str, Any]]
) -> None:
    if not findings.check(isinstance(relationships, list), "relationships must be a list"):
        return
    assert isinstance(relationships, list)

    seen: set[str] = set()
    for relationship in relationships:
        if not findings.check(
            isinstance(relationship, dict), "relationships entries must be mappings"
        ):
            continue
        assert isinstance(relationship, dict)
        name = relationship.get("name")
        where = f"relationship {name!r}"
        check_unknown_keys(findings, where, relationship, RELATIONSHIP_KEYS)

        if isinstance(name, str):
            findings.check(name not in seen, f"{where}: duplicate relationship name")
            seen.add(name)
        else:
            findings.fail("a relationship is missing its name")

        left = relationship.get("left_table")
        right = relationship.get("right_table")
        findings.check(left in tables, f"{where}: unknown left_table {left!r}")
        findings.check(right in tables, f"{where}: unknown right_table {right!r}")
        findings.check(left != right, f"{where}: a table cannot reference itself")

        if right in tables:
            findings.check(
                isinstance(tables[str(right)].get("primary_key"), dict),
                f"{where}: right_table {right!r} must declare a primary_key",
            )

        columns = relationship.get("relationship_columns")
        if findings.check(
            isinstance(columns, list) and bool(columns),
            f"{where}: relationship_columns must be a non-empty list",
        ):
            assert isinstance(columns, list)
            for pair in columns:
                findings.check(
                    isinstance(pair, dict)
                    and isinstance(pair.get("left_column"), str)
                    and isinstance(pair.get("right_column"), str),
                    f"{where}: each relationship_columns entry needs left_column and right_column",
                )

    # A star schema around a single hub keeps the model free of the circular and
    # multi-path relationships Snowflake rejects.
    right_tables = {
        relationship.get("right_table")
        for relationship in relationships
        if isinstance(relationship, dict)
    }
    findings.check(
        len(right_tables) <= 1,
        f"relationships fan into more than one hub table {sorted(map(str, right_tables))}; "
        "keep a single hub so no transitive cycle or ambiguous join path can form",
    )


def check_custom_instructions(findings: Findings, model: dict[str, Any]) -> None:
    instructions = model.get("module_custom_instructions")
    if not findings.check(
        isinstance(instructions, dict),
        "module_custom_instructions is required so the citation and cost rules travel with "
        "the semantic view",
    ):
        return
    assert isinstance(instructions, dict)
    check_unknown_keys(
        findings, "module_custom_instructions", instructions, MODULE_INSTRUCTION_KEYS
    )

    sql_generation = instructions.get("sql_generation")
    if not findings.check(
        isinstance(sql_generation, str) and bool(sql_generation),
        "module_custom_instructions.sql_generation is required",
    ):
        return
    assert isinstance(sql_generation, str)

    lowered = sql_generation.lower()
    required = {
        "run_id citation rule": "run_id",
        "session_id citation rule": "session_id",
        "user_id scoping rule": "user_id",
        "timestamp citation rule": "timestamp",
        "unpriced-call disclosure rule": "unpriced_model_call_count",
        "no-inferred-price rule": "never",
        "account usage prohibition": "account usage",
    }
    for label, needle in required.items():
        findings.check(
            needle in lowered,
            f"module_custom_instructions.sql_generation is missing the {label} "
            f"(expected to mention {needle!r})",
        )


def check_verified_queries(findings: Findings, model: dict[str, Any]) -> None:
    queries = model.get("verified_queries")
    if queries is None:
        return
    if not findings.check(isinstance(queries, list), "verified_queries must be a list"):
        return
    assert isinstance(queries, list)

    for query in queries:
        if not findings.check(isinstance(query, dict), "verified_queries entries must be mappings"):
            continue
        assert isinstance(query, dict)
        name = query.get("name")
        where = f"verified query {name!r}"
        check_unknown_keys(findings, where, query, VERIFIED_QUERY_KEYS)
        findings.check(isinstance(name, str) and bool(name), "a verified query is missing its name")
        findings.check(
            isinstance(query.get("question"), str) and bool(query.get("question")),
            f"{where}: missing question",
        )
        sql = query.get("sql")
        if not findings.check(isinstance(sql, str) and bool(sql), f"{where}: missing sql"):
            continue
        assert isinstance(sql, str)
        stripped = strip_sql_comments(sql).strip()
        findings.check(
            stripped.upper().startswith("SELECT"),
            f"{where}: sql must be a SELECT statement",
        )
        findings.check(
            "SEMANTIC_VIEW(" in stripped.upper(),
            f"{where}: sql must query the semantic view through SEMANTIC_VIEW(...)",
        )
        findings.check(
            ";" not in stripped,
            f"{where}: sql must be a single statement without a trailing semicolon",
        )


def validate(yaml_path: Path, sql_path: Path) -> list[str]:
    findings = Findings()

    raw_bytes = yaml_path.read_bytes()
    findings.check(
        not raw_bytes.startswith(b"\xef\xbb\xbf"),
        f"{yaml_path.name}: file starts with a UTF-8 BOM, which breaks dollar-quoted "
        "deployment through SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML",
    )
    raw = raw_bytes.decode("utf-8")
    findings.check(
        "$$" not in raw,
        f"{yaml_path.name}: contains '$$', which would terminate the dollar-quoted string "
        "the deployment script builds",
    )

    try:
        model = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return [f"{yaml_path.name}: YAML parse error: {exc}"]

    if not isinstance(model, dict):
        return [f"{yaml_path.name}: top level must be a mapping"]

    check_unknown_keys(findings, yaml_path.name, model, TOP_LEVEL_KEYS)
    findings.check(
        isinstance(model.get("name"), str) and bool(model.get("name")),
        f"{yaml_path.name}: missing semantic view name",
    )
    findings.check(
        isinstance(model.get("description"), str) and bool(model.get("description")),
        f"{yaml_path.name}: missing description",
    )

    views = parse_view_columns(sql_path, findings)

    raw_tables = model.get("tables")
    if not findings.check(
        isinstance(raw_tables, list) and bool(raw_tables),
        f"{yaml_path.name}: tables must be a non-empty list",
    ):
        return findings.errors
    assert isinstance(raw_tables, list)

    seen_names: dict[str, str] = {}
    tables: dict[str, dict[str, Any]] = {}
    for table in raw_tables:
        if not findings.check(
            isinstance(table, dict), f"{yaml_path.name}: tables entries must be mappings"
        ):
            continue
        assert isinstance(table, dict)
        name = check_table(findings, table, views, seen_names)
        if name is not None:
            findings.check(name not in tables, f"duplicate logical table name {name!r}")
            tables[name] = table

    findings.check(
        "sessions" in tables,
        "the model must expose a 'sessions' logical table as the caregiver reporting hub",
    )
    for required_table in (
        "sessions",
        "assistance_events",
        "model_usage",
        "replay_evidence",
        "provider_sync",
        "escalations",
    ):
        findings.check(
            required_table in tables,
            f"required logical table {required_table!r} is missing from the model",
        )

    check_relationships(findings, model.get("relationships", []), tables)
    check_custom_instructions(findings, model)
    check_verified_queries(findings, model)

    # Cost honesty: any metric reporting a monetary amount must aggregate one of the gated
    # verified projections. Metrics that merely count sessions by cost status, or average a
    # reduction ratio, are not monetary and are exempt.
    for table_name, table in tables.items():
        for metric in table.get("metrics", []) or []:
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("name", "")).lower()
            expr = str(metric.get("expr", ""))
            is_monetary = name.endswith("_usd") or "cost_usd" in name or "_amount" in name
            if is_monetary:
                findings.check(
                    "verified_cost_usd" in expr
                    or "actual_cost_usd" in expr
                    or "verified_amount" in expr,
                    f"table {table_name} metric {metric.get('name')!r} reports a monetary amount "
                    "but does not aggregate a verified, rate-card-backed column",
                )

    return findings.errors


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    analyst_root = here.parent
    yaml_path = (
        Path(argv[1]).resolve()
        if len(argv) > 1
        else analyst_root / "semantic" / "caregiver_reporting.yaml"
    )
    sql_path = (
        Path(argv[2]).resolve()
        if len(argv) > 2
        else analyst_root / "migrations" / "011_analyst_reporting_views.sql"
    )

    for path in (yaml_path, sql_path):
        if not path.is_file():
            print(f"missing required file: {path}", file=sys.stderr)
            return 2

    errors = validate(yaml_path, sql_path)
    if errors:
        print(f"semantic model validation failed with {len(errors)} problem(s):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"semantic model validation passed: {yaml_path.name} against {sql_path.name}")
    print(
        "This is static validation only. It does not prove the semantic view compiles in "
        "Snowflake; the deployment script runs SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML with "
        "verify_only=TRUE for that."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
