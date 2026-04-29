import sqlite3
import json

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# Tüm adımları oku
rows = c.execute("SELECT id, config FROM core_sapprocessstep WHERE config LIKE ? OR config LIKE ?", 
                 ('%Drive%', '%/aa%')).fetchall()

print(f"Updating {len(rows)} steps...")
updated = 0

for step_id, cfg_json in rows:
    try:
        cfg = json.loads(cfg_json)
        changed = False
        
        # Tüm keys'de yolları değiştir
        for key in cfg:
            if isinstance(cfg[key], str):
                old_val = cfg[key]
                # Hem \ hem / formatlarını değiştir
                new_val = old_val.replace("H:\\Drive'ım\\aa", "C:\\Temp")
                new_val = new_val.replace("H:/Drive'ım/aa", "C:/Temp")
                new_val = new_val.replace("H:\\Drive'ım\\aa\\", "C:\\Temp\\")
                new_val = new_val.replace("H:/Drive'ım/aa/", "C:/Temp/")
                
                if new_val != old_val:
                    cfg[key] = new_val
                    changed = True
                    print(f"  Step {step_id} {key}: {old_val[:50]} -> {new_val[:50]}")
        
        if changed:
            new_cfg_json = json.dumps(cfg, ensure_ascii=False)
            c.execute("UPDATE core_sapprocessstep SET config = ? WHERE id = ?", 
                     (new_cfg_json, step_id))
            updated += 1
    except Exception as e:
        print(f"Error processing step {step_id}: {e}")

conn.commit()
print(f"\nTotal updated: {updated}")
conn.close()
