-- Origin: the retired dispatch queue schema, migration 0017 failure_class enum.
-- Historical enum values retained as local L1 source data; this is not a live database migration.
CHECK (failure_class IN (
    'missing_substrate', 'auth_failure', 'provider_quota', 'missing_tool',
    'artifact_transport', 'protocol_violation', 'reference_resolution',
    'producer_answer_delivery', 'capability_preflight', 'crash_timeout'
));
