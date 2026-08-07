-- WebAccessible Cortex Analyst caregiver reporting: isolated schema.
--
-- This schema is the only object namespace the Analyst application owns. It never
-- writes to WEBACCESSIBLE.APP, and the already-live WEBACCESSIBLE.APP.WEBACCESSIBLE_CAREGIVER
-- Streamlit entity and its WEBACCESSIBLE_STREAMLIT_STAGE are not referenced here.
--
-- Every statement is CREATE ... IF NOT EXISTS or CREATE OR REPLACE so repeated runs
-- converge on the same state.

USE DATABASE WEBACCESSIBLE;

CREATE SCHEMA IF NOT EXISTS ANALYST
    COMMENT = 'Read-only Cortex Analyst caregiver reporting layer over verified WEBACCESSIBLE.APP views.';

USE SCHEMA ANALYST;

-- Dedicated stage for the Analyst Streamlit entity. Kept separate from
-- WEBACCESSIBLE.APP.WEBACCESSIBLE_STREAMLIT_STAGE so that a --prune deployment of
-- either application can never delete the other application's artifacts.
CREATE STAGE IF NOT EXISTS WEBACCESSIBLE_ANALYST_STAGE
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Artifacts for the WEBACCESSIBLE_CAREGIVER_ANALYST Streamlit entity only.';
