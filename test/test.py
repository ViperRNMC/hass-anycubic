#!/usr/bin/env python3
import http.client
import json
import time

# --- CONFIGURATIE ---
moonraker_host = "10.0.3.246"
moonraker_port = 7125

spoolman_host = "10.0.0.150"
spoolman_port = 7912

bay_to_location = {
    0: "ACE Pro 0",
    1: "ACE Pro 1",
    2: "ACE Pro 2",
    3: "ACE Pro 3"
}

poll_interval = 5  # seconden tussen checks
current_active_location = None

print("Start ACE Pro auto-switch (zonder requests). Ctrl+C om te stoppen.")

while True:
    try:
        # --- Moonraker API: actieve bay ophalen ---
        conn = http.client.HTTPConnection(moonraker_host, moonraker_port, timeout=5)
        conn.request("GET", "/printer/toolhead")
        response = conn.getresponse()
        if response.status != 200:
            print(f"[ERROR] Moonraker HTTP {response.status}")
            time.sleep(poll_interval)
            continue
        data = json.loads(response.read().decode())
        conn.close()

        # Extruder bay uitlezen
        active_bay = int(data.get("toolhead", {}).get("extruder_bay", -1))
        if active_bay == -1:
            print("[WARNING] 'extruder_bay' niet gevonden in Moonraker response")
            time.sleep(poll_interval)
            continue

        location = bay_to_location.get(active_bay)
        if location is None:
            print(f"[WARNING] Bay {active_bay} niet in mapping")
            time.sleep(poll_interval)
            continue

        # --- Spoolman API: actieve spool instellen ---
        if location != current_active_location:
            payload = json.dumps({"location": location})
            headers = {"Content-type": "application/json"}
            conn2 = http.client.HTTPConnection(spoolman_host, spoolman_port, timeout=5)
            conn2.request("POST", "/api/set_active_spool_by_location", body=payload, headers=headers)
            resp2 = conn2.getresponse()
            resp_text = resp2.read().decode()
            conn2.close()

            if resp2.status == 200:
                print(f"[OK] Active spool set to {location}")
                current_active_location = location
            else:
                print(f"[FOUT] Spoolman HTTP {resp2.status}: {resp_text}")

    except Exception as e:
        print(f"[ERROR] {e}")

    time.sleep(poll_interval)