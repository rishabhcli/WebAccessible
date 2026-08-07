-- WebAccessible Cortex Analyst caregiver reporting: optional grants.
--
-- Applied only when ANALYST_APPLY_GRANTS=1 is set for scripts/deploy-cortex-analyst.sh.
-- It is separated from 010/011 because granting a SNOWFLAKE database role normally
-- requires ACCOUNTADMIN, and a privilege failure must not make the schema/view
-- deployment non-idempotent.
--
-- This file reads the SQL session variable ANALYST_ROLE, which the deployment script
-- prepends. Streamlit in Snowflake runs with owner's rights, so ANALYST_ROLE must be the
-- role that owns the Streamlit entity. To run this file on its own, set it first:
--
--   SET ANALYST_ROLE = 'WEBACCESSIBLE_APP_ROLE';

USE DATABASE WEBACCESSIBLE;

-- Cortex Analyst access. CORTEX_ANALYST_USER is the narrower of the two documented
-- database roles; it grants Cortex Analyst only, not every Covered AI feature.
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_ANALYST_USER TO ROLE IDENTIFIER($ANALYST_ROLE);

-- Read-only access to the Analyst reporting layer. These are no-ops when the
-- deploying role already owns the objects.
GRANT USAGE ON SCHEMA WEBACCESSIBLE.ANALYST TO ROLE IDENTIFIER($ANALYST_ROLE);
GRANT SELECT ON VIEW WEBACCESSIBLE.ANALYST.V_CAREGIVER_SESSION TO ROLE IDENTIFIER($ANALYST_ROLE);
GRANT SELECT ON VIEW WEBACCESSIBLE.ANALYST.V_CAREGIVER_ASSISTANCE_EVENT TO ROLE IDENTIFIER($ANALYST_ROLE);
GRANT SELECT ON VIEW WEBACCESSIBLE.ANALYST.V_CAREGIVER_MODEL_USAGE TO ROLE IDENTIFIER($ANALYST_ROLE);
GRANT SELECT ON VIEW WEBACCESSIBLE.ANALYST.V_CAREGIVER_REPLAY_EVIDENCE TO ROLE IDENTIFIER($ANALYST_ROLE);
GRANT SELECT ON VIEW WEBACCESSIBLE.ANALYST.V_CAREGIVER_PROVIDER_SYNC TO ROLE IDENTIFIER($ANALYST_ROLE);
GRANT SELECT ON VIEW WEBACCESSIBLE.ANALYST.V_CAREGIVER_ESCALATION TO ROLE IDENTIFIER($ANALYST_ROLE);
GRANT SELECT ON SEMANTIC VIEW WEBACCESSIBLE.ANALYST.CAREGIVER_REPORTING TO ROLE IDENTIFIER($ANALYST_ROLE);

-- The Analyst layer is read-only. No INSERT, UPDATE, DELETE, or OWNERSHIP grant on
-- WEBACCESSIBLE.APP is required or granted here.
