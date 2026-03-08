import requests
import time
import json
from datetime import datetime, timedelta

# Consistent Headers for your MacBook M1
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Accept': 'application/json'
}

def get_haftarah_data(y, m, d):
    url = f"https://www.sefaria.org/api/calendars?year={y}&month={m}&day={d}"
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                parasha_name = ""
                haftarah_info = None
                
                for item in data.get("calendar_items", []):
                    # We need the Parasha name to use as a key
                    if item["title"]["en"] == "Parashat Hashavua":
                        parasha_name = item["displayValue"]["en"]
                    
                    # Grab the Haftarah item
                    if item["title"]["en"] == "Haftarah":
                        haftarah_info = {
                            "ref": item["ref"],
                            "display": item["displayValue"]["en"]
                        }
                
                if parasha_name and haftarah_info:
                    return parasha_name, haftarah_info
                    
            elif response.status_code == 429:
                time.sleep(10)
        except:
            pass
        time.sleep(2)
    return None, None

def build_haftarah_library():
    # Start Oct 18, 2025 (Bereshit)
    current_date = datetime(2025, 10, 18)
    haftarah_library = {}

    print("--- 📖 Building Haftarah Library ---")
    
    for week in range(54):
        p_name, h_data = get_haftarah_data(current_date.year, current_date.month, current_date.day)
        
        if p_name and p_name not in haftarah_library:
            haftarah_library[p_name] = h_data
            print(f"[{week+1}/54] Saved Haftarah for: {p_name}")
        
        current_date += timedelta(days=7)
        time.sleep(1.0) # Respectful delay

    # Save to file
    with open('haftarah_library.json', 'w', encoding='utf-8') as f:
        json.dump(haftarah_library, f, ensure_ascii=False, indent=4)
    
    print("\n✅ DONE! 'haftarah_library.json' created.")

if __name__ == "__main__":
    build_haftarah_library()