# Final demo script (about 7 minutes)

Open the dashboard (http://localhost:8501, or https://<your-domain> on AWS).

1. Log in as `viewer@cloudpulse.local`. Show section 1 (all services healthy) and section 2 (flat charts).
   Point out the Inject fault button is disabled for this role.
2. Log out, log in as `developer@cloudpulse.local`. Sidebar: Service = payment-api, click **Inject fault**.
3. Within ~5 seconds: CPU, memory and latency jump; the health card turns red (risk > 80, Critical).
4. Section 3: an incident appears with a recommended action; the ML score says anomaly True.
   Show the alert email arriving (SQS -> Lambda -> SNS) if configured.
5. As developer, try Approve: it is disabled. Log out and log in as `analyst@cloudpulse.local`.
6. Click **Approve**, then **Execute approved action**. Metrics fall back to normal; after 3 normal
   samples the incident resolves by itself.
7. Section 4: choose the incident and read the Incident Replay timeline aloud (it names who approved).
8. Section 5: show the cost and waste report flagging batch-worker as under-used.
9. Close with the audit row: http://<host>:8003/remediations needs a login token, so show the
   dashboard's "approved by" text or the database table `remediations`.
