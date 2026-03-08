from flask import Flask, render_template, request, url_for, redirect
import requests
import re
from html import unescape

app = Flask(__name__)

# Hebrew aliyah names in order
ALIYAH_NAMES = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שביעי', 'מפטיר']
ALIYAH_NAMES_EN = ['Rishon', 'Sheni', 'Shlishi', 'Revi\'i', 'Chamishi', 'Shishi', 'Shevi\'i', 'Maftir']


# ── Fetch & cache weekly parasha once at startup ──────────────────────────────
def fetch_weekly_parasha():
    data = requests.get("https://www.sefaria.org/api/calendars").json()
    result = {}
    for item in data['calendar_items']:
        title = item['title']['en']
        if title == 'Parashat Hashavua':
            result['parasha'] = {
                'ref':    item['ref'],
                'name':   item['displayValue']['en'],
                'aliyot': item.get('extraDetails', {}).get('aliyot', []),
            }
        elif title == 'Haftarah':
            result['haftarah'] = {
                'ref':    item['ref'],
                'name':   item['displayValue']['en'],
                'aliyot': [],
            }
    return result

WEEKLY = fetch_weekly_parasha()


# ── Text cleaning ─────────────────────────────────────────────────────────────
# Removes HTML tags, then decodes HTML entities (&thinsp; ׃ &nbsp; etc.)
# and strips leftover whitespace/punctuation artifacts
_ENTITY_RE = re.compile(r'&[a-zA-Z]+;|&#\d+;|&#x[0-9a-fA-F]+;')
_SEFARIA_PUNCT = re.compile(r'[׃]')   # sof pasuk — keep or remove as you like

def clean_verse(text):
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)   # strip HTML tags
    text = unescape(text)                  # decode &nbsp; &thinsp; etc.
    text = _ENTITY_RE.sub('', text)        # remove any remaining entities
    text = text.replace('\u00a0', ' ')     # non-breaking space → regular space
    text = text.replace('\u2009', ' ')     # thin space → regular space
    return text.strip()

def flatten_verses(node):
    """Recursively flatten nested Hebrew text into a flat list of verse strings."""
    if not node:
        return []
    if isinstance(node[0], str):
        return [clean_verse(v) for v in node if v]
    return [v for sub in node for v in flatten_verses(sub)]

def get_description(raw):
    if isinstance(raw, dict):
        return raw.get('en', '')
    return raw or ''


# ── Parse a ref range into (chapter, start_verse, end_verse) ─────────────────
def parse_ref_range(ref):
    """
    Given e.g. "Exodus 21:1-21:19" or "Exodus 21:1-19",
    return (chapter, first_verse, last_verse) as ints — all 1-indexed global verse nums
    handled later when we know chapter offsets.
    We return the raw ref string too so the template can show it.
    """
    return ref  # we resolve to verse indices after fetching


# ── Build aliyah boundaries from refs ────────────────────────────────────────
def ref_to_verse_range(aliyah_ref, chapter_offsets):
    """
    Convert an aliyah ref like "Exodus 21:1-21:19" into (start_global, end_global)
    1-indexed into the flat verses list.
    chapter_offsets: dict of chapter_num -> first global verse index (1-based)
    """
    # Match "Book Ch:V-Ch:V" or "Book Ch:V-V"
    m = re.search(r'(\d+):(\d+)-(\d+):(\d+)', aliyah_ref)
    if not m:
        m2 = re.search(r'(\d+):(\d+)-(\d+)$', aliyah_ref)
        if m2:
            ch = int(m2.group(1))
            v_start = int(m2.group(2))
            v_end   = int(m2.group(3))
            offset  = chapter_offsets.get(ch, 1)
            return (offset + v_start - 1, offset + v_end - 1)
        return None

    ch_start = int(m.group(1)); v_start = int(m.group(2))
    ch_end   = int(m.group(3)); v_end   = int(m.group(4))
    off_start = chapter_offsets.get(ch_start, 1)
    off_end   = chapter_offsets.get(ch_end,   1)
    return (off_start + v_start - 1, off_end + v_end - 1)


# ── Main data fetcher ─────────────────────────────────────────────────────────
def get_section_data(ref, aliyot_refs=None):
    """
    Returns:
      verses  – list of {num, text, media_url, description, anchor, aliyah_index}
      aliyot  – list of {name_he, name_en, start, end}  (1-indexed into verses)
    """
    # ── Text ──
    text_data = requests.get(f"https://www.sefaria.org/api/texts/{ref}").json()
    raw_he    = text_data.get('he', [])

    # Build chapter offsets so we can map aliyah refs to flat verse indices
    # raw_he may be [[v,v,...], [v,v,...]] (chapters) or [v,v,...] (single chapter)
    chapter_offsets = {}
    global_idx = 1
    if raw_he and isinstance(raw_he[0], list):
        # multi-chapter
        first_chapter = text_data.get('textDepth', 2)  # unused
        # figure out chapter numbering from the ref  e.g. "Exodus 21:1-24:18"
        m = re.search(r'(\d+):', ref)
        first_ch = int(m.group(1)) if m else 1
        for ci, ch in enumerate(raw_he):
            chapter_offsets[first_ch + ci] = global_idx
            global_idx += len([v for v in ch if v])
    else:
        m = re.search(r'(\d+)', ref)
        chapter_offsets[int(m.group(1)) if m else 1] = 1

    verses_flat = flatten_verses(raw_he)

    # ── Recordings ──
    media_list = requests.get(
        f"https://www.sefaria.org/api/related/{ref}"
    ).json().get('media', [])

    recordings_by_verse = {}
    for rec in media_list:
        anchor = rec.get('anchorRef', '')
        m = re.search(r':(\d+)', anchor)
        if m:
            vnum = int(m.group(1))
            if vnum not in recordings_by_verse:
                recordings_by_verse[vnum] = {
                    'media_url':   rec.get('media_url', ''),
                    'description': get_description(rec.get('description', '')),
                    'anchor':      anchor,
                }

    # ── Aliyot boundaries ──
    aliyot = []
    if aliyot_refs:
        for i, aref in enumerate(aliyot_refs):
            rng = ref_to_verse_range(aref, chapter_offsets)
            if rng:
                aliyot.append({
                    'name_he': ALIYAH_NAMES[i]    if i < len(ALIYAH_NAMES)    else f'עלייה {i+1}',
                    'name_en': ALIYAH_NAMES_EN[i]  if i < len(ALIYAH_NAMES_EN) else f'Aliyah {i+1}',
                    'start':   rng[0],
                    'end':     rng[1],
                    'ref':     aref,
                })

    # ── Zip everything ──
    verses = []
    for i, text in enumerate(verses_flat, start=1):
        rec = recordings_by_verse.get(i)
        # find which aliyah this verse belongs to
        aliyah_idx = None
        for ai, al in enumerate(aliyot):
            if al['start'] <= i <= al['end']:
                aliyah_idx = ai
                break
        verses.append({
            'num':         i,
            'text':        text,
            'media_url':   rec['media_url']   if rec else '',
            'description': rec['description'] if rec else '',
            'anchor':      rec['anchor']       if rec else '',
            'aliyah_idx':  aliyah_idx,
        })

    return verses, aliyot


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', weekly=WEEKLY)


@app.route('/read')
def read():
    ref        = request.args.get('ref')
    name       = request.args.get('name', ref)
    aliyot_key = request.args.get('section')   # 'parasha' or 'haftarah'

    if not ref:
        return redirect(url_for('index'))

    aliyot_refs = []
    if aliyot_key and aliyot_key in WEEKLY:
        aliyot_refs = WEEKLY[aliyot_key].get('aliyot', [])

    verses, aliyot = get_section_data(ref, aliyot_refs)
    return render_template(
        'parasha.html',
        name=name,
        ref=ref,
        verses=verses,
        aliyot=aliyot,
    )


if __name__ == '__main__':
    app.run(debug=True, port=5000)