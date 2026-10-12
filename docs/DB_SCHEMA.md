# Database schema (created automatically by the services at startup)

| Table | Owner service | Purpose |
| --- | --- | --- |
| users(id, name, email, password_hash, role, status, created_at) | auth-service | logins; passwords stored as scrypt hashes |
| metrics(id, service, ts, cpu, memory, latency_ms, error_rate, request_count) | metrics-service | raw metric history |
| incidents(id, service, severity, risk_score, status, opened_at, resolved_at, normal_streak) | incident-service | one row per incident |
| incident_events(id, incident_id, event_type, message, ts) | incident-service | the Incident Replay timeline |
| remediations(id, incident_id, service, action, status, recommended_at, approved_by, approved_at, executed_at, result, verified) | remediation-service | audit log of fixes |
| demo_state(service, fault) | remediation-service | simulated fault switch for the demo |
