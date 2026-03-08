"""
sefaria.py — Torah library + Sefaria API helpers for ScroLein.

torah_library.json is the source of truth. Sefer keys are:
  "Bereshit", "Shemot", "Vayikra", "Bamidbar", "Devarim"
"""

import json, re, os, requests
from html import unescape

HEADERS      = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
LIBRARY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'torah_library.json')
TIMEOUT      = 8

ALIYAH_LABELS = [
    "First Aliyah", "Second Aliyah", "Third Aliyah", "Fourth Aliyah",
    "Fifth Aliyah", "Sixth Aliyah", "Seventh Aliyah", "Maftir"
]

# Ordered sefer list — must match keys in torah_library.json exactly
SFARIM = ["Bereshit", "Shemot", "Vayikra", "Bamidbar", "Devarim"]

_library = None  # in-memory cache


def get_library():
    global _library
    if _library is not None:
        return _library
    if not os.path.exists(LIBRARY_FILE):
        raise FileNotFoundError(
            f"torah_library.json not found at {LIBRARY_FILE}."
        )
    with open(LIBRARY_FILE, 'r', encoding='utf-8') as f:
        _library = json.load(f)
    total = sum(len(v) for v in _library.values())
    print(f"[sefaria] Loaded library: {total} parshiot")
    return _library


def get_parasha_list():
    """Return [{sefer, name, aliyah_count}, ...] in reading order."""
    lib = get_library()
    result = []
    for sefer in SFARIM:
        for name, data in lib.get(sefer, {}).items():
            result.append({
                "sefer": sefer,
                "name": name,
                "aliyah_count": len(data.get("aliyot", [])),
            })
    return result


def get_parshiot_by_sefer():
    """Return {sefer: [name, ...], ...} — for the two-step assign form."""
    lib = get_library()
    return {sefer: list(lib.get(sefer, {}).keys()) for sefer in SFARIM}


def get_aliyah_ref(parasha_name, aliyah_label):
    """Return the Sefaria ref for one aliyah, e.g. 'Exodus 22:4-22:26'."""
    lib = get_library()
    for sefer in SFARIM:
        if parasha_name in lib.get(sefer, {}):
            data   = lib[sefer][parasha_name]
            aliyot = data.get("aliyot", [])
            try:
                idx = ALIYAH_LABELS.index(aliyah_label)
                return aliyot[idx] if idx < len(aliyot) else data["ref"]
            except ValueError:
                return data["ref"]
    print(f"[sefaria] WARNING: Parasha not found in library: '{parasha_name}'")
    return None


def get_aliyot_for_parasha(parasha_name):
    """Return the list of aliyah refs for a parasha, or [] if not found."""
    lib = get_library()
    for sefer in SFARIM:
        if parasha_name in lib.get(sefer, {}):
            return lib[sefer][parasha_name].get("aliyot", [])
    print(f"[sefaria] WARNING: Parasha not found: '{parasha_name}'")
    return []


# ── Verse fetching ────────────────────────────────────────────────────────────

def clean_verse(text):
    if not text: return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'&[a-zA-Z]+;|&#\d+;|&#x[0-9a-fA-F]+;', '', text)
    return text.replace('\u00a0', ' ').replace('\u2009', ' ').strip()


def _parse_ref_bounds(ref):
    """Parse start/end (chapter, verse) from refs like 'Exodus 21:1-21:19'."""
    # Full cross-chapter range: "21:1-22:5"
    m = re.search(r'(\d+):(\d+)-(\d+):(\d+)', ref)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    # Same-chapter range: "21:1-19"
    m = re.search(r'(\d+):(\d+)-(\d+)$', ref)
    if m:
        ch = int(m.group(1))
        return ch, int(m.group(2)), ch, int(m.group(3))
    # Single verse: "21:1"
    m = re.search(r'(\d+):(\d+)', ref)
    if m:
        return int(m.group(1)), int(m.group(2)), None, None
    return 1, 1, None, None


def get_verses_for_ref(ref):
    """
    Fetch Hebrew text + matched audio recordings for any Sefaria ref.

    Uses context=0 so Sefaria returns ONLY the requested verse range.
    Also trims output to exact bounds as a safety net.
    Uses params dict so requests handles URL encoding automatically.

    Returns a list of verse dicts.
    """
    if not ref:
        return []

    start_ch, start_v, end_ch, end_v = _parse_ref_bounds(ref)

    try:
        resp = requests.get(
            f"https://www.sefaria.org/api/texts/{ref}",
            params={"context": "0"},
            headers=HEADERS,
            timeout=TIMEOUT
        ).json()
        raw_he = resp.get('he', [])
    except Exception as e:
        print(f"[sefaria] texts API failed for '{ref}': {e}")
        return []

    try:
        media_list = requests.get(
            f"https://www.sefaria.org/api/related/{ref}",
            headers=HEADERS,
            timeout=TIMEOUT
        ).json().get('media', [])
    except Exception as e:
        print(f"[sefaria] related API failed for '{ref}': {e}")
        media_list = []

    # Build (chapter, verse) → recording map using anchorRefExpanded
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

    verses   = []
    seq      = 1
    is_multi = raw_he and isinstance(raw_he[0], list)

    if is_multi:
        for ch_offset, ch_verses in enumerate(raw_he):
            ch     = start_ch + ch_offset
            v_base = (start_v - 1) if ch_offset == 0 else 0
            for i, raw_v in enumerate(ch_verses):
                text = clean_verse(raw_v)
                if not text: continue
                v = v_base + i + 1
                # Safety trim: skip verses outside the requested range
                if end_ch is not None and end_v is not None:
                    if ch > end_ch or (ch == end_ch and v > end_v):
                        continue
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
            v = start_v + i
            # Safety trim
            if end_v is not None and v > end_v:
                continue
            rec = recordings.get((start_ch, v), {})
            verses.append({'num': seq, 'chapter': start_ch, 'verse': v, 'text': text,
                           'media_url': rec.get('media_url', ''),
                           'anchor': rec.get('anchor', f'{start_ch}:{v}'),
                           'description': rec.get('description', ''),
                           'aliyah_idx': None})
            seq += 1

    return verses