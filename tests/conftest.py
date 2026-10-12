import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
for svc in ("incident-service", "metrics-service", "remediation-service", "auth-service"):
    sys.path.insert(0, str(ROOT / "services" / svc))
sys.path.insert(0, str(ROOT / "lambda" / "notify"))

# One throw-away SQLite file shared by all services in the tests (no Docker needed).
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["MODEL_DIR"] = str(ROOT / "ml" / "models")
os.environ["JWT_SECRET"] = "test-secret-for-unit-tests-only-0123456789"
os.environ["INTERNAL_KEY"] = "test-internal-key"
os.environ["SEED_PASSWORD"] = "Demo12345"
os.environ["INCIDENT_URL"] = "http://127.0.0.1:9"      # nothing listens here: tests never call out
os.environ["REMEDIATION_URL"] = "http://127.0.0.1:9"
for name in ("SQS_QUEUE_URL", "SNS_TOPIC_ARN", "S3_BUCKET"):
    os.environ.pop(name, None)
