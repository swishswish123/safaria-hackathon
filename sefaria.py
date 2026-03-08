"""
sefaria.py — Torah library + Sefaria API helpers for ScroLein.

The torah_library.json file is the source of truth for all parasha/aliyah refs.
It is built once by calling build_library() and saved to disk.
After that, everything works offline from the JSON.

Structure of torah_library.json:
{
    "Bereishit": {
        "Bereishit": {"ref": "Genesis 1:1-6:8", "aliyot": [...8 refs...], "haftarah": "..."},
        "Noach":     {"ref": "Genesis 6:9-11:32", "aliyot": [...], "haftarah": "..."},
        ...
    },
    "Shemot": { ... },
    ...
}
"""

import json, re, os, time, requests
from html import unescape
from datetime import datetime, timedelta

HEADERS      = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
LIBRARY_FILE = os.path.join(os.path.dirname(__file__), 'torah_library.json')
TIMEOUT      = 8

ALIYAH_LABELS = [
    "First Aliyah", "Second Aliyah", "Third Aliyah", "Fourth Aliyah",
    "Fifth Aliyah", "Sixth Aliyah", "Seventh Aliyah", "Maftir"
]

BOOK_TO_SEFER = {
    "Genesis": "Bereishit", "Exodus": "Shemot", "Leviticus": "Vayikra",
    "Numbers": "Bamidbar", "Deuteronomy": "Devarim",
}


# ── Library: load or build ────────────────────────────────────────────────────

_library = None  # cached in memory after first load

def get_library():
    """Load torah_library.json from disk (or memory cache). Build it if missing."""
    global _library
    if _library is not None:
        return _library
    if os.path.exists(LIBRARY_FILE):
        with open(LIBRARY_FILE, 'r') as f:
            _library = json.load(f)
        print(f"[sefaria] Loaded library: {sum(len(v) for v in _library.values())} parshiot")
        return _library
    # Not found — build it now (takes ~1 min)
    _library = build_library()
    return _library


def build_library():
    """
    Fetch all parshiot from the Sefaria calendar API by walking 60 consecutive
    Saturdays starting from the most recent one.  Saves result to torah_library.json.
    """
    print("[sefaria] Building Torah library from Sefaria API (this takes ~60 seconds)...")
    library = {s: {} for s in BOOK_TO_SEFER.values()}

    # Find the most recent Saturday
    today = datetime.today()
    days_back = (today.weekday() + 2) % 7  # days since last Saturday
    saturday  = today - timedelta(days=days_back)

    for i in range(60):
        d = saturday + timedelta(weeks=i)
        date_str = d.strftime('%Y-%m-%d')
        try:
            data = requests.get(
                "https://www.sefaria.org/api/calendars",
                params={"date": date_str},
                headers=HEADERS,
                timeout=TIMEOUT
            ).json()
        except Exception as e:
            print(f"[sefaria]  Week {i}: request failed ({e})")
            time.sleep(0.5)
            continue

        parasha  = next((x for x in data.get('calendar_items', []) if x['title']['en'] == 'Parashat Hashavua'), None)
        haftarah = next((x for x in data.get('calendar_items', []) if x['title']['en'] == 'Haftarah'), None)

        if not parasha:
            time.sleep(0.3)
            continue

        name  = parasha['displayValue']['en']
        ref   = parasha['ref']
        aliyot = parasha.get('extraDetails', {}).get('aliyot', [])
        haftarah_ref = haftarah['ref'] if haftarah else None

        book  = ref.split()[0]
        sefer = BOOK_TO_SEFER.get(book, "Bereishit")

        if name not in library[sefer]:
            library[sefer][name] = {"ref": ref, "aliyot": aliyot, "haftarah": haftarah_ref}
            print(f"[sefaria]  + {sefer} / {name}  ({ref})")

        time.sleep(0.3)

    with open(LIBRARY_FILE, 'w') as f:
        json.dump(library, f, indent=2, ensure_ascii=False)

    total = sum(len(v) for v in library.values())
    print(f"[sefaria] Library built: {total} parshiot saved to {LIBRARY_FILE}")
    return library


# ── Public API ────────────────────────────────────────────────────────────────

def get_parasha_list():
    """
    Return all parshiot as an ordered list for the assign.html dropdown:
        [{"en": "Bereishit", "sefer": "Bereishit"}, ...]
    Order within each sefer is preserved from the library (reading order).
    """
    lib = get_library()
    result = []
    for sefer, parshiot in lib.items():
        for name in parshiot:
            result.append({"en": name, "sefer": sefer})
    return result


def get_aliyah_ref(parasha_name, aliyah_label):
    """
    Return the exact Sefaria ref for one aliyah of a parasha.
    e.g. get_aliyah_ref("Mishpatim", "Third Aliyah") → "Exodus 22:4-22:26"
    Returns None if the parasha or aliyah isn't found.
    """
    lib = get_library()
    for sefer in lib:
        if parasha_name in lib[sefer]:
            data   = lib[sefer][parasha_name]
            aliyot = data.get("aliyot", [])
            try:
                idx = ALIYAH_LABELS.index(aliyah_label)
                return aliyot[idx] if idx < len(aliyot) else data["ref"]
            except ValueError:
                return data["ref"]
    print(f"[sefaria] Parasha not found in library: '{parasha_name}'")
    return None


def get_aliyot_for_parasha(parasha_name):
    """Return the list of 8 aliyah refs for a parasha, or [] if not found."""
    lib = get_library()
    for sefer in lib:
        if parasha_name in lib[sefer]:
            return lib[sefer][parasha_name].get("aliyot", [])
    return []


# ── Verse fetching ────────────────────────────────────────────────────────────

def clean_verse(text):
    """Strip HTML tags and decode entities from a Sefaria Hebrew string."""
    if not text: return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'&[a-zA-Z]+;|&#\d+;|&#x[0-9a-fA-F]+;', '', text)
    return text.replace('\u00a0', ' ').replace('\u2009', ' ').strip()


def get_verses_for_ref(ref):
    """
    Fetch Hebrew text + matched audio recordings for any Sefaria ref.

    Returns a list of verse dicts:
        {"num": 1, "chapter": 21, "verse": 1, "text": "...",
         "media_url": "...", "anchor": "Exodus 21:1",
         "description": "...", "aliyah_idx": None}
    """
    if not ref:
        return []

    # Fetch text
    try:
        raw_he = requests.get(
            f"https://www.sefaria.org/api/texts/{ref}",
            headers=HEADERS, timeout=TIMEOUT
        ).json().get('he', [])
    except Exception as e:
        print(f"[sefaria] texts API failed for '{ref}': {e}")
        return []

    # Parse starting chapter:verse from the ref
    m        = re.search(r'(\d+):(\d+)', ref)
    start_ch = int(m.group(1)) if m else 1
    start_v  = int(m.group(2)) if m else 1

    # Fetch recordings
    try:
        media_list = requests.get(
            f"https://www.sefaria.org/api/related/{ref}",
            headers=HEADERS, timeout=TIMEOUT
        ).json().get('media', [])
    except Exception as e:
        print(f"[sefaria] related API failed for '{ref}': {e}")
        media_list = []

    # Build (chapter, verse) → recording map using anchorRefExpanded
    # so ranges like "Exodus 21:1-3" correctly map to all 3 verses
    recordings = {}
    for rec in media_list:
        url      = rec.get('media_url', '')
        expanded = rec.get('anchorRefExpanded') or [rec.get('anchorRef', '')]
        for vref in expanded:
            m2 = re.search(r'(\d+):(\d+)', vref)
            if m2 and url:
                key = (int(m2.group(1)), int(m2.group(2)))
                if key not in recordings:
                    recordings[key] = {'media_url': url, 'anchor': vref,
                                       'description': rec.get('description', '')}

    # Walk through text and zip with recordings
    verses = []
    seq    = 1
    is_multi = raw_he and isinstance(raw_he[0], list)

    if is_multi:
        for ch_offset, ch_verses in enumerate(raw_he):
            ch     = start_ch + ch_offset
            v_base = (start_v - 1) if ch_offset == 0 else 0
            for i, raw_v in enumerate(ch_verses):
                text = clean_verse(raw_v)
                if not text: continue
                v   = v_base + i + 1
                rec = recordings.get((ch, v), {})
                verses.append({'num': seq, 'chapter': ch, 'verse': v, 'text': text,
                                'media_url': rec.get('media_url', ''),
                                'anchor': rec.get('anchor', f'{ch}:{v}'),
                                'description': rec.get('description', ''),
                                'aliyah_idx': None})
                seq += 1
    else:
        for i, raw_v in enumerate(raw_he):
            text = clean_verse(raw_v) if isinstance(raw_v, str) else ''
            if not text: continue
            v   = start_v + i
            rec = recordings.get((start_ch, v), {})
            verses.append({'num': seq, 'chapter': start_ch, 'verse': v, 'text': text,
                           'media_url': rec.get('media_url', ''),
                           'anchor': rec.get('anchor', f'{start_ch}:{v}'),
                           'description': rec.get('description', ''),
                           'aliyah_idx': None})
            seq += 1

    return verses