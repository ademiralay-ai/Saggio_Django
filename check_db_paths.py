import sqlite3
import json

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

print("=== Searching for Drive paths in DB ===")
rows = c.execute("SELECT id, config FROM core_sapprocessstep WHERE config LIKE ? OR config LIKE ?", 
                 ('%Drive%', '%/aa%')).fetchall()

if rows:
    for step_id, cfg_json in rows:
        print(f"\nStep {step_id}:")
        try:
            cfg = json.loads(cfg_json)
            for key, val in cfg.items():
                if 'Drive' in str(val) or '/aa' in str(val).lower():
                    print(f"  {key}: {val}")
        except:
            print(f"  Raw: {cfg_json[:200]}")
    print(f"\nTotal steps with Drive paths: {len(rows)}")
else:
    print("No Drive paths found in DB")

conn.close()
