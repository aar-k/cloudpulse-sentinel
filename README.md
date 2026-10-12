# CloudPulse Sentinel

Observe, Understand, Respond: detects abnormal service metrics, scores incident risk
(rules + Isolation Forest ML), opens incidents with a replayable timeline, alerts through
SQS + Lambda + SNS email, and runs approved, non-destructive remediation behind a login.

```
simulator -> metrics-service -> incident-service (risk score + ML) -> PostgreSQL
                                   |-> SQS queue -> Lambda -> SNS email
                                   \-> remediation-service (approve -> execute -> verify)
auth-service issues JWT logins; every service checks them
dashboard (Streamlit, behind Caddy HTTPS on AWS) reads all services
```

## Run locally (needs Docker Desktop)
```
copy .env.example .env        (Windows)   |   cp .env.example .env   (Mac/Linux)
docker compose up --build
```
Dashboard http://localhost:8501. Log in as `admin@cloudpulse.local`, `analyst@cloudpulse.local`,
`developer@cloudpulse.local` or `viewer@cloudpulse.local` with the `SEED_PASSWORD` from `.env`.
APIs (each has interactive docs at /docs): 8001 metrics, 8002 incidents, 8003 remediation, 8004 auth.

## Tests (no Docker needed, use Python 3.12)
```
python -m pip install -r requirements-dev.txt
python -m pytest -q
```
`python tests/load_test.py --key <INTERNAL_KEY>` runs a simple load test.

## Retrain the ML model
`python ml/train.py` (writes ml/models/*, prints precision/recall/F1).

## Deploy on AWS
Follow the guide. EC2 + RDS PostgreSQL + S3 + SQS + Lambda + SNS; HTTPS with Caddy;
auto-deploy from GitHub Actions through AWS Systems Manager. `infrastructure/terraform`
describes the core network, server, database and bucket as code.

## Roles
| Role | Can |
| --- | --- |
| admin | everything, including creating users |
| analyst | approve and execute fixes, resolve incidents, inject demo faults |
| developer | inject demo faults, view everything |
| readonly | view only |
| automation | internal services only (X-Internal-Key), cannot log in |

## Safety
Only `restart_service` and `scale_service` exist, both act on the simulated demo service, need an
admin/analyst approval, and are written to an audit table. The remediation service has no AWS
permissions. Secrets live in `.env` (ignored by Git).

## Known limitations
Data is synthetic. Terraform covers the core infrastructure only (queue, Lambda and SNS are made in
the console). Single environment (no staging). Kubernetes is future scope.


## Running without Docker (if Docker will not start on your laptop)

    python -m pip install -r requirements-local.txt
    python run_local.py            # add --reset to wipe the local database first

Open http://localhost:8501 . Everything runs as plain Python programs with a local SQLite file;
Ctrl+C stops it all. Logs are in the `logs/` folder. Use Docker on the AWS server as usual.
