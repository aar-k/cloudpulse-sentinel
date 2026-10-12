"""CloudPulse Command Center (Streamlit). Log in with a user from the auth service."""
import os

import httpx
import pandas as pd
import streamlit as st

AUTH = os.getenv("AUTH_URL", "http://localhost:8004")
METRICS = os.getenv("METRICS_URL", "http://localhost:8001")
INCIDENT = os.getenv("INCIDENT_URL", "http://localhost:8002")
REMED = os.getenv("REMEDIATION_URL", "http://localhost:8003")
SERVICES = ["payment-api", "auth-api", "orders-api", "batch-worker"]
DEMO_TARGETS = SERVICES[:3]          # services you may break on purpose

st.set_page_config(page_title="CloudPulse Sentinel", layout="wide")


def headers():
    return {"Authorization": f"Bearer {st.session_state.get('token', '')}"}


def get(url, default=None):
    try:
        r = httpx.get(url, headers=headers(), timeout=5)
        if r.status_code == 401:
            st.session_state.pop("token", None)       # token expired: back to the login page
            st.rerun()
        return r.json() if r.status_code == 200 else default
    except httpx.HTTPError:
        return default


def post(url, payload=None):
    try:
        r = httpx.post(url, json=payload or {}, headers=headers(), timeout=8)
        return r.status_code, r.json()
    except httpx.HTTPError as exc:
        return 0, {"detail": str(exc)}


def login_page():
    st.title("CloudPulse Sentinel")
    st.caption("Observe - Understand - Respond")
    left, _ = st.columns([1, 2])
    with left:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            go = st.form_submit_button("Log in", type="primary")
        if go:
            try:
                r = httpx.post(f"{AUTH}/login", json={"email": email, "password": password}, timeout=8)
            except httpx.HTTPError:
                st.error("Cannot reach the auth service. Is it running?")
                return
            if r.status_code == 200:
                data = r.json()
                st.session_state.update(token=data["access_token"], name=data["name"], role=data["role"])
                st.rerun()
            else:
                st.error("Wrong email or password")
        st.caption("Demo accounts: admin@, analyst@, developer@, viewer@ + cloudpulse.local")


if "token" not in st.session_state:
    login_page()
    st.stop()

role = st.session_state["role"]
user = st.session_state["name"]
can_approve = role in ("admin", "analyst")
can_break = role in ("admin", "analyst", "developer")

st.title("CloudPulse Sentinel - Command Center")

with st.sidebar:
    st.header("You")
    st.write(f"**{user}**")
    st.write(f"Role: `{role}`")
    if st.button("Log out"):
        for k in ("token", "name", "role"):
            st.session_state.pop(k, None)
        st.rerun()
    st.caption("Admin and analyst can approve fixes. Developer can inject a fault. Read-only can only view.")
    st.header("Demo controls")
    target = st.selectbox("Service", DEMO_TARGETS)
    c1, c2 = st.columns(2)
    if c1.button("Inject fault", type="primary", disabled=not can_break):
        post(f"{REMED}/demo/fault", {"service": target, "on": True})
    if c2.button("Clear fault", disabled=not can_break):
        post(f"{REMED}/demo/fault", {"service": target, "on": False})
    live = st.toggle("Auto-refresh every 3 s", value=True)


def render():
    # ---- 1. health cards ----
    st.subheader("1. Service health")
    latest = {x["service"]: x for x in (get(f"{INCIDENT}/latest", []) or [])}
    cols = st.columns(len(SERVICES))
    for col, s in zip(cols, SERVICES):
        x = latest.get(s)
        with col:
            if not x:
                st.metric(s, "no data")
                continue
            ml = x.get("ml", {})
            st.metric(s, f"{x['health_score']}", delta=f"risk {x['risk_score']} ({x['severity']})",
                      delta_color="inverse")
            m = x["metrics"]
            st.caption(f"CPU {m['cpu']:.0f}% | mem {m['memory']:.0f}% | "
                       f"{m['latency_ms']:.0f} ms | err {m['error_rate']:.1f}%")
            if ml.get("available"):
                st.caption(f"ML anomaly: {ml['anomaly']} (score {ml['anomaly_score']})")

    # ---- 2. live chart ----
    st.subheader("2. Live metrics")
    chart_service = st.selectbox("Chart service", SERVICES, key="chart_service")
    rows = get(f"{METRICS}/metrics/{chart_service}?limit=120", []) or []
    if rows:
        df = pd.DataFrame(rows).set_index("ts")
        a, b = st.columns(2)
        a.line_chart(df[["cpu", "memory"]], height=220)
        b.line_chart(df[["latency_ms"]], height=220)
    else:
        st.info("No metrics yet. Is the simulator running?")

    # ---- 3. incidents + approvals ----
    st.subheader("3. Incidents")
    incs = get(f"{INCIDENT}/incidents", []) or []
    rems = {r["incident_id"]: r for r in (get(f"{REMED}/remediations", []) or [])}
    if not incs:
        st.success("No incidents. Click 'Inject fault' in the sidebar to create one.")
    for inc in incs[:8]:
        rem = rems.get(inc["id"])
        label = f"{inc['id']} - {inc['service']} - {inc['severity']} (risk {inc['risk_score']}) - {inc['status']}"
        with st.expander(label, expanded=(inc["status"] == "open")):
            if rem:
                st.write(f"Recommended action: **{rem['action']}** | status: **{rem['status']}**"
                         f" | approved by: {rem['approved_by'] or '-'} | verified: {rem['verified']}")
                if rem["status"] == "recommended":
                    if st.button("Approve", key=f"ap{rem['id']}", disabled=not can_approve):
                        code, body = post(f"{REMED}/remediations/{rem['id']}/approve")
                        if code != 200:
                            st.error(body.get("detail"))
                if rem["status"] == "approved":
                    if st.button("Execute approved action", key=f"ex{rem['id']}", disabled=not can_approve):
                        post(f"{REMED}/remediations/{rem['id']}/execute")
            else:
                st.caption("No remediation recommended yet.")

    # ---- 4. incident replay ----
    st.subheader("4. Incident Replay")
    if incs:
        pick = st.selectbox("Choose an incident", [i["id"] for i in incs], key="replay_pick")
        data = get(f"{INCIDENT}/incidents/{pick}/replay")
        if data:
            st.caption(f"{data['incident']['service']} - {data['incident']['status']} - "
                       f"opened {data['incident']['opened_at']}")
            for e in data["events"]:
                st.markdown(f"`{e['ts'][11:19]}` **{e['event_type']}** - {e['message']}")

    # ---- 5. cost and waste ----
    st.subheader("5. Cost and waste report (last 24 h)")
    waste = get(f"{METRICS}/analytics/waste", []) or []
    if waste:
        df = pd.DataFrame(waste)[["service", "instance_type", "avg_cpu", "peak_cpu", "underutilized",
                                  "recommendation", "estimated_monthly_saving_usd", "reason"]]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("Prices are example list prices for illustration, not your real AWS bill.")
    else:
        st.caption("Not enough data yet.")


if live:
    st.fragment(run_every=3)(render)()
else:
    render()
