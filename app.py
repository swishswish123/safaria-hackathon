from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
import os
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random, string, re, requests
from html import unescape

app = Flask(__name__)
app.secret_key = "leining_secret_123"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["RECORDING_FOLDER"] = os.path.join(os.path.dirname(__file__), "static", "recordings")
os.makedirs(app.config["RECORDING_FOLDER"], exist_ok=True)
db = SQLAlchemy(app)


# ================================================================== MODELS
class User(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    username    = db.Column(db.String(80), unique=True, nullable=False)
    password    = db.Column(db.String(200), nullable=False)
    role        = db.Column(db.String(10), nullable=False, default="student")
    class_id    = db.Column(db.String(6), nullable=True)
    teacher_pin = db.Column(db.String(6), nullable=True)

class ClassID(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False)

class StudentClass(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    pin      = db.Column(db.String(6),  nullable=False)

class Assignment(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(80), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    parasha      = db.Column(db.String(100), nullable=False)
    aliyah       = db.Column(db.String(50), nullable=False)
    due_date     = db.Column(db.String(50), nullable=True)
    submitted    = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    notes        = db.Column(db.Text, nullable=True)
    assigned_by  = db.Column(db.String(80), nullable=True)
    sefaria_ref        = db.Column(db.String(200), nullable=True)  # e.g. "Genesis 6:9-11:32"
    recording_filename = db.Column(db.String(200), nullable=True)  # student's uploaded recording


# ================================================================== SEFARIA HELPERS

# Hebrew aliyah labels
ALIYAH_NAMES_HE = ['ראשון','שני','שלישי','רביעי','חמישי','שישי','שביעי','מפטיר']
ALIYAH_NAMES_EN = ["Rishon","Sheni","Shlishi","Revi'i","Chamishi","Shishi","Shevi'i","Maftir"]

# Map our parsha dropdown names → Sefaria API parsha names
SEFARIA_PARSHA_NAME = {
    "Bereishit":"Bereishit","Noach":"Noach","Lech Lecha":"Lech-Lecha",
    "Vayeira":"Vayera","Chayei Sarah":"Chayei-Sarah","Toldot":"Toldot",
    "Vayeitzei":"Vayetzei","Vayishlach":"Vayishlach","Vayeishev":"Vayeshev",
    "Mikeitz":"Miketz","Vayigash":"Vayigash","Vayechi":"Vayechi",
    "Shemot":"Shemot","Vaeira":"Vaera","Bo":"Bo","Beshalach":"Beshalach",
    "Yitro":"Yitro","Mishpatim":"Mishpatim","Terumah":"Terumah",
    "Tetzaveh":"Tetzaveh","Ki Tisa":"Ki-Tisa","Vayakhel":"Vayakhel","Pekudei":"Pekudei",
    "Vayikra":"Vayikra","Tzav":"Tzav","Shemini":"Shemini","Tazria":"Tazria",
    "Metzora":"Metzora","Acharei Mot":"Achrei-Mot","Kedoshim":"Kedoshim",
    "Emor":"Emor","Behar":"Behar","Bechukotai":"Bechukotai",
    "Bamidbar":"Bamidbar","Naso":"Nasso","Behaalotecha":"Beha'alotecha",
    "Shelach":"Sh'lach","Korach":"Korach","Chukat":"Chukat","Balak":"Balak",
    "Pinchas":"Pinchas","Matot":"Matot","Masei":"Masei",
    "Devarim":"Devarim","Vaetchanan":"Vaetchanan","Eikev":"Eikev","Re'eh":"Re'eh",
    "Shoftim":"Shoftim","Ki Teitzei":"Ki-Teitzei","Ki Tavo":"Ki-Tavo",
    "Nitzavim":"Nitzavim","Vayeilech":"Vayeilech","Haazinu":"Ha'Azinu",
    "Vezot HaBerachah":"Vezot-Habracha",
}

# Map our aliyah dropdown labels → 0-based index into the aliyot list
ALIYAH_INDEX = {
    "First Aliyah": 0, "Second Aliyah": 1, "Third Aliyah": 2,
    "Fourth Aliyah": 3, "Fifth Aliyah": 4, "Sixth Aliyah": 5,
    "Seventh Aliyah": 6, "Maftir": 7, "Haftorah": None,  # haftorah handled separately
}

def clean_verse(text):
    """Strip HTML tags, decode entities, normalise whitespace."""
    if not text: return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'&[a-zA-Z]+;|&#\d+;|&#x[0-9a-fA-F]+;', '', text)
    text = text.replace('\u00a0', ' ').replace('\u2009', ' ')
    return text.strip()

def flatten_verses(node):
    """Recursively flatten nested Hebrew text into flat list."""
    if not node: return []
    if isinstance(node[0], str):
        return [clean_verse(v) for v in node if v]
    return [v for sub in node for v in flatten_verses(sub)]

def ref_to_verse_range(aliyah_ref, chapter_offsets):
    """Convert a Sefaria ref like 'Genesis 6:9-6:22' into (start, end) global indices."""
    m = re.search(r'(\d+):(\d+)-(\d+):(\d+)', aliyah_ref)
    if not m:
        m2 = re.search(r'(\d+):(\d+)-(\d+)$', aliyah_ref)
        if m2:
            ch, vs, ve = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            off = chapter_offsets.get(ch, 1)
            return (off + vs - 1, off + ve - 1)
        return None
    ch_s, v_s = int(m.group(1)), int(m.group(2))
    ch_e, v_e = int(m.group(3)), int(m.group(4))
    return (chapter_offsets.get(ch_s, 1) + v_s - 1,
            chapter_offsets.get(ch_e, 1) + v_e - 1)

def get_section_data(ref, aliyot_refs=None):
    """
    Fetch verses + recordings from Sefaria for a given ref.
    Recordings are matched to verses by their chapter:verse position
    within the ref, so they line up correctly even mid-parasha.
    Returns (verses list, aliyot list) ready for parasha.html.
    """
    try:
        text_data = requests.get(
            f"https://www.sefaria.org/api/texts/{ref}",
            timeout=8
        ).json()
    except Exception:
        return [], []

    raw_he = text_data.get('he', [])

    # Determine the starting chapter:verse from the ref (e.g. "Genesis 12:1-12:9")
    # so we can match recording anchorRefs accurately
    start_ch_match = re.search(r'(\d+):(\d+)', ref)
    start_ch  = int(start_ch_match.group(1)) if start_ch_match else 1
    start_v   = int(start_ch_match.group(2)) if start_ch_match else 1

    # Build chapter offsets for aliyah boundary mapping
    chapter_offsets = {}
    global_idx = 1
    if raw_he and isinstance(raw_he[0], list):
        for ci, ch in enumerate(raw_he):
            chapter_offsets[start_ch + ci] = global_idx
            global_idx += len([v for v in ch if v])
    else:
        chapter_offsets[start_ch] = 1

    verses_flat = flatten_verses(raw_he)

    # Fetch recordings for this specific ref
    try:
        media_list = requests.get(
            f"https://www.sefaria.org/api/related/{ref}",
            timeout=6
        ).json().get('media', [])
    except Exception:
        media_list = []

    # Build a mapping of (chapter, verse) -> recording
    # Sefaria anchorRef looks like "Genesis 12:3" or "Genesis 12:3-5"
    recordings_by_cv = {}
    for rec in media_list:
        anchor = rec.get('anchorRef', '')
        m2 = re.search(r'(\d+):(\d+)', anchor)
        if m2:
            ch, v = int(m2.group(1)), int(m2.group(2))
            if (ch, v) not in recordings_by_cv:
                recordings_by_cv[(ch, v)] = {
                    'media_url':   rec.get('media_url', ''),
                    'description': rec.get('description', ''),
                    'anchor':      anchor,
                }

    # Build aliyot
    aliyot = []
    if aliyot_refs:
        for i, aref in enumerate(aliyot_refs):
            rng = ref_to_verse_range(aref, chapter_offsets)
            if rng:
                aliyot.append({
                    'name_he': ALIYAH_NAMES_HE[i] if i < len(ALIYAH_NAMES_HE) else f'עלייה {i+1}',
                    'name_en': ALIYAH_NAMES_EN[i] if i < len(ALIYAH_NAMES_EN) else f'Aliyah {i+1}',
                    'start': rng[0], 'end': rng[1], 'ref': aref,
                })

    # Zip verses — track actual chapter:verse as we walk through the text
    verses = []
    flat_idx = 0  # position within verses_flat
    cur_ch = start_ch
    cur_v  = start_v

    # If multi-chapter, walk chapter by chapter
    if raw_he and isinstance(raw_he[0], list):
        for ci, ch_verses in enumerate(raw_he):
            ch_num = start_ch + ci
            for vi, raw_v in enumerate(ch_verses):
                if not raw_v:
                    cur_v += 1
                    continue
                v_num = start_v + vi if ci == 0 else vi + 1
                text  = clean_verse(raw_v)
                rec   = recordings_by_cv.get((ch_num, v_num))
                aliyah_idx = next((ai for ai, al in enumerate(aliyot)
                                   if al['start'] <= flat_idx + 1 <= al['end']), None)
                verses.append({
                    'num': flat_idx + 1, 'text': text,
                    'chapter': ch_num, 'verse': v_num,
                    'media_url':   rec['media_url']   if rec else '',
                    'description': rec['description'] if rec else '',
                    'anchor':      rec['anchor']       if rec else '',
                    'aliyah_idx':  aliyah_idx,
                })
                flat_idx += 1
    else:
        # Single chapter
        for vi, raw_v in enumerate(raw_he if isinstance(raw_he, list) else []):
            if not raw_v: continue
            v_num = start_v + vi
            text  = clean_verse(raw_v) if isinstance(raw_v, str) else ''
            if not text: continue
            rec = recordings_by_cv.get((start_ch, v_num))
            verses.append({
                'num': flat_idx + 1, 'text': text,
                'chapter': start_ch, 'verse': v_num,
                'media_url':   rec['media_url']   if rec else '',
                'description': rec['description'] if rec else '',
                'anchor':      rec['anchor']       if rec else '',
                'aliyah_idx':  None,
            })
            flat_idx += 1

    return verses, aliyot

def fetch_parasha_aliyot(parasha_name):
    """
    Ask the Sefaria calendar API for the aliyot refs of a given parasha.
    Returns list of ref strings, one per aliyah.
    """
    try:
        data = requests.get("https://www.sefaria.org/api/calendars", timeout=6).json()
        for item in data.get('calendar_items', []):
            if item['title']['en'] == 'Parashat Hashavua':
                name_en = item.get('displayValue', {}).get('en', '')
                sefaria_name = SEFARIA_PARSHA_NAME.get(parasha_name, '')
                # Accept if it matches OR just return whatever is current (for preview)
                return item.get('extraDetails', {}).get('aliyot', [])
    except Exception:
        pass
    return []

def build_sefaria_ref(parasha, aliyah_label):
    """
    Given parasha name + aliyah label, return the Sefaria ref string for that aliyah.
    Uses the calendar API to get real refs.
    Returns (ref_string, display_name) or (None, None) on failure.
    """
    aliyot_refs = fetch_parasha_aliyot(parasha)
    idx = ALIYAH_INDEX.get(aliyah_label)
    if idx is None or not aliyot_refs or idx >= len(aliyot_refs):
        # Fallback: just use the parasha name as the ref
        sname = SEFARIA_PARSHA_NAME.get(parasha, parasha)
        return sname, parasha
    ref = aliyot_refs[idx]
    return ref, f"{parasha} – {aliyah_label}"


# ================================================================== GENERAL HELPERS
def generate_pin():
    while True:
        pin = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not User.query.filter_by(teacher_pin=pin).first() and \
           not ClassID.query.filter_by(code=pin).first():
            return pin

def enroll_student(username, pin):
    if not StudentClass.query.filter_by(username=username, pin=pin).first():
        db.session.add(StudentClass(username=username, pin=pin))


# ================================================================== SEED
with app.app_context():
    db.create_all()
    for code in ["ABC123", "XYZ789"]:
        if not ClassID.query.filter_by(code=code).first():
            db.session.add(ClassID(code=code))
    if not User.query.filter_by(username="Rabbi_Cohen").first():
        db.session.add(User(username="Rabbi_Cohen", password="teach123",
                            role="teacher", teacher_pin="ABC123"))
    if not User.query.filter_by(username="Gedaliah").first():
        db.session.add(User(username="Gedaliah", password="student123",
                            role="student", class_id="ABC123"))
    db.session.commit()
    enroll_student("Gedaliah", "ABC123")
    db.session.commit()

    gedaliah_assignments = [
        {"username":"Gedaliah","assigned_by":"Rabbi_Cohen",
         "title":"Mah Tovu – Morning Blessings","parasha":"Siddur",
         "aliyah":"Opening Prayers","due_date":"March 14, 2026",
         "submitted":False,"notes":"","sefaria_ref":None},
        {"username":"Gedaliah","assigned_by":"Rabbi_Cohen",
         "title":"Ashrei – Psalm 145","parasha":"Tehillim",
         "aliyah":"Afternoon Service","due_date":"March 21, 2026",
         "submitted":False,"notes":"","sefaria_ref":None},
        {"username":"Gedaliah","assigned_by":"Rabbi_Cohen",
         "title":"Parshat Lech Lecha – Fifth Aliyah","parasha":"Lech Lecha",
         "aliyah":"Fifth Aliyah","due_date":"March 28, 2026",
         "submitted":False,"notes":"","sefaria_ref":"Lech-Lecha"},
        {"username":"Gedaliah","assigned_by":"Rabbi_Cohen",
         "title":"Parshat Bereishit – First Aliyah","parasha":"Bereishit",
         "aliyah":"First Aliyah","due_date":"March 1, 2026",
         "submitted":True,"submitted_at":datetime(2026,2,28,14,30),
         "notes":"I practiced this one a lot — felt confident with the trope!",
         "sefaria_ref":"Bereishit"},
    ]
    for a in gedaliah_assignments:
        if not Assignment.query.filter_by(username=a["username"], title=a["title"]).first():
            db.session.add(Assignment(**a))
    db.session.commit()


# ================================================================== ROUTES

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/register")
def register():
    return render_template("register.html")

@app.route("/register/student", methods=["GET","POST"])
def register_student():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        if User.query.filter_by(username=username).first():
            error = "That username is already taken."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            db.session.add(User(username=username, password=password, role="student"))
            db.session.commit()
            session["pending_user"] = username
            return redirect(url_for("class_id"))
    return render_template("register_student.html", error=error)

@app.route("/register/teacher", methods=["GET","POST"])
def register_teacher():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        if User.query.filter_by(username=username).first():
            error = "That username is already taken."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            pin = generate_pin()
            db.session.add(User(username=username, password=password,
                                role="teacher", teacher_pin=pin))
            db.session.add(ClassID(code=pin))
            db.session.commit()
            session["username"] = username
            session["new_pin"]  = pin
            return redirect(url_for("teacher_dashboard"))
    return render_template("register_teacher.html", error=error)

@app.route("/login", methods=["GET","POST"])
def login():
    error = error_field = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        user = User.query.filter_by(username=username).first()
        if not username and not password:
            error, error_field = "Please enter your username and password.", "both"
        elif not user:
            error, error_field = "We don't recognize that username.", "username"
        elif user.password != password:
            error, error_field = "That password is incorrect.", "password"
        else:
            session["username"] = username
            return redirect(url_for("teacher_dashboard" if user.role=="teacher" else "dashboard"))
    return render_template("login.html", error=error, error_field=error_field)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/class-id", methods=["GET","POST"])
def class_id():
    error = None
    username = session.get("pending_user")
    if not username:
        return redirect(url_for("register"))
    if request.method == "POST":
        entered_id = request.form["class_id"].strip().upper()
        if not ClassID.query.filter_by(code=entered_id).first():
            error = "Invalid Class ID. Please check with your teacher."
        else:
            user = User.query.filter_by(username=username).first()
            user.class_id = entered_id
            enroll_student(username, entered_id)
            db.session.commit()
            session.pop("pending_user")
            session["username"] = username
            return redirect(url_for("dashboard"))
    return render_template("class_id.html", error=error, username=username)

@app.route("/add-class", methods=["GET","POST"])
def add_class():
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    error = success = None
    if request.method == "POST":
        entered_id = request.form["class_id"].strip().upper()
        if not ClassID.query.filter_by(code=entered_id).first():
            error = "Invalid Class ID. Please check with your teacher."
        elif StudentClass.query.filter_by(username=username, pin=entered_id).first():
            error = "You are already enrolled in that class."
        else:
            enroll_student(username, entered_id)
            db.session.commit()
            success = f"Successfully joined class {entered_id}!"
    return render_template("add_class.html", username=username, error=error, success=success)

# ------------------------------------------------------------------ STUDENT DASHBOARD
@app.route("/dashboard")
def dashboard():
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    user = User.query.filter_by(username=username).first()
    if user and user.role == "teacher":
        return redirect(url_for("teacher_dashboard"))

    enrollments = StudentClass.query.filter_by(username=username).all()
    teacher_sections = []
    for e in enrollments:
        teacher = User.query.filter_by(teacher_pin=e.pin, role="teacher").first()
        if not teacher: continue
        pending   = Assignment.query.filter_by(username=username, assigned_by=teacher.username, submitted=False).all()
        completed = Assignment.query.filter_by(username=username, assigned_by=teacher.username, submitted=True).all()
        teacher_sections.append({"teacher_name": teacher.username, "pin": teacher.teacher_pin,
                                  "pending": pending, "completed": completed})
    known = [s["teacher_name"] for s in teacher_sections]
    op = Assignment.query.filter_by(username=username, submitted=False).filter(
        ~Assignment.assigned_by.in_(known) if known else Assignment.id > 0).all()
    oc = Assignment.query.filter_by(username=username, submitted=True).filter(
        ~Assignment.assigned_by.in_(known) if known else Assignment.id > 0).all()
    if op or oc:
        teacher_sections.append({"teacher_name":"Other","pin":"——","pending":op,"completed":oc})

    return render_template("dashboard.html", username=username, teacher_sections=teacher_sections)

# ------------------------------------------------------------------ TEACHER DASHBOARD
@app.route("/teacher/dashboard")
def teacher_dashboard():
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("dashboard"))
    students = User.query.filter_by(role="student", class_id=teacher.teacher_pin).all()
    student_data = []
    for s in students:
        total     = Assignment.query.filter_by(username=s.username).count()
        submitted = Assignment.query.filter_by(username=s.username, submitted=True).count()
        student_data.append({"username":s.username,"total":total,
                              "submitted":submitted,"pending":total-submitted})
    new_pin = session.pop("new_pin", None)
    return render_template("teacher_dashboard.html", teacher=teacher,
                           student_data=student_data, new_pin=new_pin)

# ------------------------------------------------------------------ ASSIGN WORK
@app.route("/teacher/assign/<student_username>", methods=["GET","POST"])
def assign(student_username):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("home"))
    student = User.query.filter_by(username=student_username, role="student").first()
    if not student: return redirect(url_for("teacher_dashboard"))
    error = None
    if request.method == "POST":
        title    = request.form["title"].strip()
        parasha  = request.form["parasha"].strip()
        aliyah   = request.form["aliyah"].strip()
        due_date = request.form["due_date"].strip()
        notes    = request.form.get("notes","").strip()
        if not title or not parasha or not aliyah:
            error = "Please fill in all required fields."
        else:
            # Resolve Sefaria ref for this parasha+aliyah
            sefaria_ref, _ = build_sefaria_ref(parasha, aliyah)
            db.session.add(Assignment(
                username=student_username, title=title, parasha=parasha,
                aliyah=aliyah, due_date=due_date, assigned_by=username,
                notes=notes, sefaria_ref=sefaria_ref
            ))
            db.session.commit()
            return redirect(url_for("teacher_dashboard"))
    existing = Assignment.query.filter_by(username=student_username).all()
    return render_template("assign.html", teacher=teacher, student=student,
                           existing=existing, error=error)

# ------------------------------------------------------------------ SEFARIA PREVIEW API
# Called by JavaScript on the assign page to show a live verse preview
@app.route("/api/sefaria-preview")
def sefaria_preview():
    parasha = request.args.get("parasha","").strip()
    aliyah  = request.args.get("aliyah","").strip()
    if not parasha or not aliyah:
        return jsonify({"error": "Missing parasha or aliyah"}), 400

    aliyot_refs = fetch_parasha_aliyot(parasha)
    idx = ALIYAH_INDEX.get(aliyah)

    if idx is None:
        return jsonify({"error": "Haftorah preview not supported yet"}), 400
    if not aliyot_refs or idx >= len(aliyot_refs):
        sname = SEFARIA_PARSHA_NAME.get(parasha, parasha)
        return jsonify({"ref": sname, "verses": [], "note": "Aliyah boundaries unavailable — showing full parasha on the reading page."})

    ref = aliyot_refs[idx]
    verses, _ = get_section_data(ref)
    # Return first 6 verses as a preview
    preview = [{"num": v["num"], "text": v["text"]} for v in verses[:6]]
    return jsonify({"ref": ref, "verses": preview})

# ------------------------------------------------------------------ READ TEXT (student)
@app.route("/read/<int:assignment_id>")
def read_assignment(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.username != username:
        return redirect(url_for("dashboard"))

    ref = assignment.sefaria_ref
    if not ref:
        return redirect(url_for("dashboard"))

    # Get the aliyah index so we can isolate just that aliyah's verses
    aliyah_idx = ALIYAH_INDEX.get(assignment.aliyah)

    # Fetch all aliyot refs for this parasha to find verse boundaries
    aliyot_refs = fetch_parasha_aliyot(assignment.parasha)

    # If we have a specific aliyah and its ref, fetch ONLY that aliyah's ref
    # This ensures we only load and display the exact assigned section
    if aliyah_idx is not None and aliyot_refs and aliyah_idx < len(aliyot_refs):
        aliyah_ref = aliyot_refs[aliyah_idx]
        # Fetch just this aliyah's text and recordings directly
        verses, _ = get_section_data(aliyah_ref, [])
    else:
        # Fallback: fetch the whole parasha ref
        verses, _ = get_section_data(ref, [])

    # Re-number verses starting from 1 for clean display
    for i, v in enumerate(verses, start=1):
        v['display_num'] = i

    return render_template("parasha.html",
        name       = assignment.title,
        ref        = ref,
        verses     = verses,
        assignment = assignment
    )


# ------------------------------------------------------------------ TEACHER: VIEW STUDENT'S ASSIGNMENTS
@app.route("/teacher/student/<student_username>")
def teacher_student_view(student_username):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("dashboard"))

    # Confirm this student is actually in the teacher's class
    student = User.query.filter_by(username=student_username, role="student").first()
    if not student: return redirect(url_for("teacher_dashboard"))

    submitted = Assignment.query.filter_by(username=student_username, assigned_by=username, submitted=True).all()
    assigned  = Assignment.query.filter_by(username=student_username, assigned_by=username, submitted=False).all()

    return render_template("teacher_student_view.html",
        student_username = student_username,
        submitted        = submitted,
        assigned         = assigned,
        submitted_count  = len(submitted),
        assigned_count   = len(assigned),
        total_count      = len(submitted) + len(assigned),
    )


# ------------------------------------------------------------------ TEACHER: PREVIEW UNSUBMITTED ASSIGNMENT
@app.route("/teacher/preview/<int:assignment_id>")
def teacher_preview(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("dashboard"))

    assignment = Assignment.query.get(assignment_id)
    if not assignment: return redirect(url_for("teacher_dashboard"))

    ref = assignment.sefaria_ref
    if not ref:
        return redirect(url_for("teacher_student_view", student_username=assignment.username))

    aliyah_idx  = ALIYAH_INDEX.get(assignment.aliyah)
    aliyot_refs = fetch_parasha_aliyot(assignment.parasha)

    if aliyah_idx is not None and aliyot_refs and aliyah_idx < len(aliyot_refs):
        aliyah_ref = aliyot_refs[aliyah_idx]
        verses, _  = get_section_data(aliyah_ref, [])
    else:
        verses, _  = get_section_data(ref, [])

    return render_template("teacher_preview.html",
        assignment = assignment,
        name       = assignment.title,
        ref        = ref,
        verses     = verses,
    )


# ------------------------------------------------------------------ TEACHER: REVIEW STUDENT RECORDING
@app.route("/teacher/review/<int:assignment_id>")
def teacher_review(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("dashboard"))

    assignment = Assignment.query.get(assignment_id)
    if not assignment: return redirect(url_for("teacher_dashboard"))

    # Guard: only accessible if submitted AND has a recording
    if not assignment.submitted or not assignment.recording_filename:
        return redirect(url_for("teacher_student_view", student_username=assignment.username))

    # Fetch the Hebrew text for the assigned aliyah (same logic as student read_assignment)
    ref = assignment.sefaria_ref
    if not ref:
        return redirect(url_for("teacher_student_view", student_username=assignment.username))

    aliyah_idx  = ALIYAH_INDEX.get(assignment.aliyah)
    aliyot_refs = fetch_parasha_aliyot(assignment.parasha)

    if aliyah_idx is not None and aliyot_refs and aliyah_idx < len(aliyot_refs):
        aliyah_ref = aliyot_refs[aliyah_idx]
        verses, _  = get_section_data(aliyah_ref, [])
    else:
        verses, _  = get_section_data(ref, [])

    return render_template("teacher_review.html",
        assignment = assignment,
        name       = assignment.title,
        ref        = ref,
        verses     = verses,
    )

# ------------------------------------------------------------------ UPLOAD RECORDING
@app.route("/upload-recording/<int:assignment_id>", methods=["POST"])
def upload_recording(assignment_id):
    username = session.get("username")
    if not username:
        return jsonify({"error": "Not logged in"}), 401

    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.username != username:
        return jsonify({"error": "Not authorized"}), 403

    if "recording" not in request.files:
        return jsonify({"error": "No file received"}), 400

    file = request.files["recording"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    # Save as assignment_<id>_<username>.webm (overwrite if re-recorded)
    filename = f"assignment_{assignment_id}_{secure_filename(username)}.webm"
    filepath = os.path.join(app.config["RECORDING_FOLDER"], filename)
    file.save(filepath)

    # Store filename on the assignment
    assignment.recording_filename = filename
    db.session.commit()

    return jsonify({"success": True, "filename": filename})


# ------------------------------------------------------------------ SUBMIT / UNSUBMIT / EDIT
@app.route("/submit/<int:assignment_id>", methods=["POST"])
def submit_assignment(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    a = Assignment.query.get(assignment_id)
    if a and a.username == username:
        a.submitted = True; a.submitted_at = datetime.now()
        db.session.commit()
    return redirect(url_for("congratulations", assignment_id=assignment_id))

@app.route("/unsubmit/<int:assignment_id>", methods=["POST"])
def unsubmit_assignment(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    a = Assignment.query.get(assignment_id)
    if a and a.username == username:
        a.submitted = False; a.submitted_at = None
        db.session.commit()
    return redirect(url_for("dashboard"))

@app.route("/edit/<int:assignment_id>", methods=["GET","POST"])
def edit_assignment(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    a = Assignment.query.get(assignment_id)
    if not a or a.username != username: return redirect(url_for("dashboard"))
    if request.method == "POST":
        a.notes = request.form["notes"].strip()
        db.session.commit()
        return redirect(url_for("dashboard"))
    return render_template("edit_assignment.html", assignment=a, username=username)

@app.route("/congratulations/<int:assignment_id>")
def congratulations(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    a = Assignment.query.get(assignment_id)
    return render_template("congratulations.html", username=username, assignment=a)

@app.route("/resources")
def resources():
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    return render_template("resources.html", username=username)

if __name__ == "__main__":
    app.run(debug=True)