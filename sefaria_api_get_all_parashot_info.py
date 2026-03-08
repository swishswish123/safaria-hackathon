import requests
import time
import json
import random
from datetime import datetime, timedelta

# This tells Sefaria you are using a Mac (M1/M2/M3)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Accept': 'application/json'
}

BOOK_MAP = {
    "Genesis": "Bereshit",
    "Exodus": "Shemot",
    "Leviticus": "Vayikra",
    "Numbers": "Bamidbar",
    "Deuteronomy": "Devarim"
}

def get_parasha_data_safe(y, m, d):
    url = f"https://www.sefaria.org/api/calendars?year={y}&month={m}&day={d}"
    
    # Retry loop: if the API fails, it tries again up to 3 times
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                data = response.json()
                for item in data.get("calendar_items", []):
                    if item["title"]["en"] == "Parashat Hashavua":
                        full_ref = item["ref"]
                        book_name = full_ref.split(" ")[0]
                        sefer_key = BOOK_MAP.get(book_name, "Unknown")
                        return {
                            "sefer": sefer_key,
                            "name": item["displayValue"]["en"],
                            "ref": full_ref,
                            "aliyot": item.get("extraDetails", {}).get("aliyot", [])
                        }
            elif response.status_code == 429:
                # If rate limited, wait longer
                time.sleep(10)
        except Exception as e:
            pass
        
        time.sleep(2) # Wait between retries
    return None

def build_and_save_library():
    # Oct 18, 2025 is the first Saturday of the next cycle (Bereshit)
    current_date = datetime(2025, 10, 18)
    library = {"Bereshit": {}, "Shemot": {}, "Vayikra": {}, "Bamidbar": {}, "Devarim": {}}

    print("--- Starting Full Torah Scan ---")
    print("This will take about 2 minutes. Please wait...")
    
    for week in range(54):
        p = get_parasha_data_safe(current_date.year, current_date.month, current_date.day)
        
        if p and p['sefer'] in library:
            if p['name'] not in library[p['sefer']]:
                library[p['sefer']][p['name']] = {
                    "ref": p['ref'],
                    "aliyot": p['aliyot']
                }
                print(f"[{week+1}/54] Saved: {p['name']} to {p['sefer']}")
        
        current_date += timedelta(days=7)
        # 1.0 second delay is the "Golden Rule" to avoid getting banned by Sefaria
        time.sleep(1.0)

    # Save to your computer
    with open('torah_library.json', 'w', encoding='utf-8') as f:
        json.dump(library, f, ensure_ascii=False, indent=4)
    
    print("saved")

# Run the builder
if __name__ == "__main__":
    build_and_save_library()