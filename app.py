from flask import Flask, render_template, request, url_for, redirect
import requests
import re

app = Flask(__name__)


# ── Fetch & cache weekly parasha once at startup ──────────────────────────────
def fetch_weekly_parasha():
    data = requests.get("https://www.sefaria.org/api/calendars").json()
    result = {}
    for item in data['calendar_items']:
        title = item['title']['en']
        if title == 'Parashat Hashavua':
            result['parasha'] = {'ref': item['ref'], 'name': item['displayValue']['en']}
        elif title == 'Haftarah':
            result['haftarah'] = {'ref': item['ref'], 'name': item['displayValue']['en']}
    return result

WEEKLY = fetch_weekly_parasha()


# ── Helpers ───────────────────────────────────────────────────────────────────
def strip_html(text):
    return re.sub(r'<[^>]+>', '', text or '')

def flatten_verses(node):
    """Recursively flatten nested Hebrew text into a flat list of verse strings."""
    if not node:
        return []
    if isinstance(node[0], str):
        return [strip_html(v) for v in node if v]
    return [verse for sub in node for verse in flatten_verses(sub)]

def get_description(raw):
    """Sefaria description is sometimes a dict {'en':...}, sometimes a plain string."""
    if isinstance(raw, dict):
        return raw.get('en', '')
    return raw or ''


def get_section_data(ref):
    """
    Returns a list of verse dicts: [{text, media_url, description}, ...]
    matched by verse index from the Sefaria /related API.

    Sefaria anchorRefs look like "Genesis 1:3" or "Bereshit 1:3".
    We index them by the verse number (last integer after ':' or ' ').
    """
    # Fetch Hebrew text
    verses_raw = requests.get(f"https://www.sefaria.org/api/texts/{ref}").json().get('he', [])
    verses = flatten_verses(verses_raw)

    # Fetch recordings and key them by verse number
    media_list = requests.get(f"https://www.sefaria.org/api/related/{ref}").json().get('media', [])

    # Build map: verse_number (int) -> recording
    recordings_by_verse = {}
    for rec in media_list:
        anchor = rec.get('anchorRef', '')
        # Extract the last number — that's the verse number
        # Handles "Genesis 1:3", "Genesis 1:3-5", "Bereshit 1:3" etc.
        match = re.search(r':(\d+)', anchor)
        if match:
            verse_num = int(match.group(1))
            # Only store the first recording per verse
            if verse_num not in recordings_by_verse:
                recordings_by_verse[verse_num] = {
                    'media_url':   rec.get('media_url', ''),
                    'description': get_description(rec.get('description', '')),
                    'anchor':      anchor,
                }

    # Zip verses with their recordings (1-indexed)
    result = []
    for i, text in enumerate(verses, start=1):
        rec = recordings_by_verse.get(i)
        result.append({
            'num':         i,
            'text':        text,
            'media_url':   rec['media_url']   if rec else '',
            'description': rec['description'] if rec else '',
            'anchor':      rec['anchor']       if rec else '',
        })
    return result


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', weekly=WEEKLY)


@app.route('/read')
def read():
    """Driven by ?ref=...&name=... — works for any Sefaria ref."""
    ref  = request.args.get('ref')
    name = request.args.get('name', ref)
    if not ref:
        return redirect(url_for('index'))
    verses = get_section_data(ref)
    return render_template('parasha.html', name=name, ref=ref, verses=verses)


if __name__ == '__main__':
    app.run(debug=True, port=5000)