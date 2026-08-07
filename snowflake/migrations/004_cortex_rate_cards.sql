USE DATABASE WEBACCESSIBLE;
USE SCHEMA APP;

-- Snowflake Service Consumption Table, Table 6(a), effective August 7, 2026.
-- The account uses ANY_REGION routing, whose documented AI Credit price is $2.00.
MERGE INTO COST_RATE_CARDS AS target
USING (
    SELECT
        column1::STRING AS rate_card_id,
        column2::STRING AS rate_card_version,
        column3::STRING AS provider,
        column4::STRING AS model,
        column5::STRING AS model_version,
        column6::STRING AS token_class,
        column7::NUMBER(38, 0) AS unit_quantity,
        column8::NUMBER(38, 12) AS unit_price,
        column9::STRING AS currency,
        column10::NUMBER(38, 12) AS usd_conversion_rate,
        column11::STRING AS source_reference,
        column12::STRING AS rounding_rule,
        TO_TIMESTAMP_NTZ(column13::STRING) AS effective_from,
        column14::TIMESTAMP_NTZ AS effective_to
    FROM VALUES
        (
            'snowflake-cortex:claude-haiku-4-5:input:any-region:2026-08-07',
            'snowflake-cortex-any-region-2026-08-07',
            'snowflake_cortex',
            'claude-haiku-4-5',
            NULL,
            'input',
            1000000,
            0.60,
            'CREDITS',
            2.00,
            'https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf; Table 6(a); effective 2026-08-07; https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing; ANY_REGION',
            'no_intermediate_rounding;persist_12_decimal_places',
            '2026-08-07 00:00:00',
            NULL
        ),
        (
            'snowflake-cortex:claude-haiku-4-5:output:any-region:2026-08-07',
            'snowflake-cortex-any-region-2026-08-07',
            'snowflake_cortex',
            'claude-haiku-4-5',
            NULL,
            'output',
            1000000,
            3.00,
            'CREDITS',
            2.00,
            'https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf; Table 6(a); effective 2026-08-07; https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing; ANY_REGION',
            'no_intermediate_rounding;persist_12_decimal_places',
            '2026-08-07 00:00:00',
            NULL
        )
) AS source
ON target.rate_card_id = source.rate_card_id
WHEN NOT MATCHED THEN INSERT (
    rate_card_id,
    rate_card_version,
    provider,
    model,
    model_version,
    token_class,
    unit_quantity,
    unit_price,
    currency,
    usd_conversion_rate,
    source_reference,
    rounding_rule,
    effective_from,
    effective_to
) VALUES (
    source.rate_card_id,
    source.rate_card_version,
    source.provider,
    source.model,
    source.model_version,
    source.token_class,
    source.unit_quantity,
    source.unit_price,
    source.currency,
    source.usd_conversion_rate,
    source.source_reference,
    source.rounding_rule,
    source.effective_from,
    source.effective_to
);
