from incident_svc.risk import Sample, risk_score, severity, explain, WEIGHTS

def test_healthy_is_low():
    s = Sample(cpu=30, memory=45, latency_ms=110, error_rate=0.3, request_count=100)
    assert severity(risk_score(s)) == "Low"

def test_worst_case_is_critical_and_100():
    s = Sample(cpu=100, memory=100, latency_ms=2000, error_rate=50, request_count=500)
    assert risk_score(s) == 100.0
    assert severity(100) == "Critical"

def test_band_boundaries():
    assert severity(29.99) == "Low"
    assert severity(30) == "Moderate"
    assert severity(60) == "High"
    assert severity(80) == "Critical"

def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

def test_explain_top_signals():
    s = Sample(cpu=95, memory=40, latency_ms=100, error_rate=0, request_count=100)
    assert explain(s)["top_signals"][0] == "cpu"

def test_fault_scenario_opens_incident_level():
    s = Sample(cpu=95, memory=85, latency_ms=900, error_rate=9, request_count=220)
    assert risk_score(s) >= 60
