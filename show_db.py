"""Shows the tables and row counts in the local database (use with run_local.py, no Docker).

    python show_db.py
"""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent / "cloudpulse.db"
if not db.exists():
    raise SystemExit("cloudpulse.db not found. Start the system first: python run_local.py")
con = sqlite3.connect(db)
tables = [r[0] for r in con.execute(
    "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
print("Tables in the database:", len(tables))
for t in tables:
    n = con.execute(f"select count(*) from {t}").fetchone()[0]
    print(f"  {t:<18} {n} rows")
print("\nLatest incident_events:")
for row in con.execute("select incident_id, event_type, ts from incident_events order by id desc limit 8"):
    print("  ", row)
