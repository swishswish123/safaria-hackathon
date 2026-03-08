from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random, string, json as _json

app = Flask(__name__)
app.secret_key = "leining_secret_123"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["RECORDING_FOLDER"] = os.path.join(os.path.dirname(__file__), "static", "recordings")
os.makedirs(app.config["RECORDING_FOLDER"], exist_ok=True)
db = SQLAlchemy(app)

@app.template_filter('from_json')
def from_json_filter(s):
    try: return _json.loads(s) if s else {}
    except: return {}


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
    sefaria_ref                = db.Column(db.String(200), nullable=True)
    recording_filename         = db.Column(db.String(200), nullable=True)
    teacher_recording_filename = db.Column(db.String(200), nullable=True)
    recording_choice           = db.Column(db.String(20),  nullable=True, default='included')
    verse_grades          = db.Column(db.Text,    nullable=True)
    feedback_note         = db.Column(db.Text,    nullable=True)
    feedback_submitted    = db.Column(db.Boolean, default=False)
    feedback_seen         = db.Column(db.Boolean, default=True)
    feedback_submitted_at = db.Column(db.DateTime, nullable=True)


# ================================================================== SEFARIA HELPERS
# All Torah data comes from torah_library.json via sefaria.py.
# No live calendar API calls — every parasha and aliyah ref is pre-built.

from sefaria import (
    get_library,
    get_parasha_list,
    get_aliyah_ref,
    get_aliyot_for_parasha,
    get_verses_for_ref,
    ALIYAH_LABELS,
)

# Aliyah dropdown labels shown in the assign form
ASSIGN_ALIYAH_LABELS = [
    "First Aliyah", "Second Aliyah", "Third Aliyah", "Fourth Aliyah",
    "Fifth Aliyah", "Sixth Aliyah", "Seventh Aliyah",
]

# Map label string → 0-based index into the aliyot list
ALIYAH_INDEX = {label: i for i, label in enumerate(ASSIGN_ALIYAH_LABELS)}

def get_verses(parasha_name, aliyah_label, fallback_ref=None):
    """
    Unified verse-fetching helper used by all routes (read, review, preview,
    feedback, record-nusach).  Returns a list of verse dicts ready for templates.
    Uses the library-backed aliyah ref; falls back to fallback_ref if needed.
    """
    aliyah_ref = get_aliyah_ref(parasha_name, aliyah_label)
    if aliyah_ref:
        return get_verses_for_ref(aliyah_ref)
    if fallback_ref:
        return get_verses_for_ref(fallback_ref)
    return []

def build_sefaria_ref(parasha, aliyah_label):
    """
    Return the exact Sefaria ref string for one aliyah of a parasha.
    Used when saving a new assignment.
    """
    ref = get_aliyah_ref(parasha, aliyah_label)
    if ref:
        return ref, f"{parasha} – {aliyah_label}"
    # Fallback: use the whole-parasha ref from the library
    lib = get_library()
    for sefer in lib:
        if parasha in lib[sefer]:
            return lib[sefer][parasha]["ref"], parasha
    return parasha, parasha


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
         "title":"Parshat Bereishit – First Aliyah","parasha":"Bereshit",
         "aliyah":"First Aliyah","due_date":"March 1, 2026",
         "submitted":True,"submitted_at":datetime(2026,2,28,14,30),
         "notes":"I practiced this one a lot — felt confident with the trope!",
         "sefaria_ref":"Genesis 1:1-2:3"},
    ]
    for a in gedaliah_assignments:
        if not Assignment.query.filter_by(username=a["username"], title=a["title"]).first():
            db.session.add(Assignment(**a))
    db.session.commit()


# ================================================================== ROUTES

@app.route("/")
def home():
    return render_template("shared/home.html")

@app.route("/register")
def register():
    return render_template("shared/register.html")

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
    return render_template("shared/register_student.html", error=error)

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
    return render_template("shared/register_teacher.html", error=error)

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
    return render_template("shared/login.html", error=error, error_field=error_field)

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
    return render_template("shared/class_id.html", error=error, username=username)

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
    return render_template("student/add_class.html", username=username, error=error, success=success)


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
        all_assignments = Assignment.query.filter_by(username=username, assigned_by=teacher.username).all()
        pending   = [a for a in all_assignments if not a.submitted and not a.feedback_submitted]
        completed = [a for a in all_assignments if a.submitted and not a.feedback_submitted]
        feedback_list = []
        for a in all_assignments:
            if not a.feedback_submitted: continue
            try:
                g = _json.loads(a.verse_grades) if a.verse_grades else {}
            except:
                g = {}
            vals = list(g.values())
            a._grade_perfect = vals.count('perfect')
            a._grade_some    = vals.count('some')
            a._grade_work    = vals.count('work')
            feedback_list.append(a)
        teacher_sections.append({
            "teacher_name": teacher.username,
            "pin":          teacher.teacher_pin,
            "pending":      pending,
            "completed":    completed,
            "feedback":     feedback_list,
        })

    known = [s["teacher_name"] for s in teacher_sections]
    other_q = Assignment.query.filter_by(username=username)
    if known:
        other_q = other_q.filter(~Assignment.assigned_by.in_(known))
    other_all = other_q.all()
    if other_all:
        teacher_sections.append({
            "teacher_name": "Other",
            "pin":          "——",
            "pending":      [a for a in other_all if not a.submitted and not a.feedback_submitted],
            "completed":    [a for a in other_all if a.submitted and not a.feedback_submitted],
            "feedback":     [a for a in other_all if a.feedback_submitted],
        })

    new_feedback = Assignment.query.filter_by(
        username=username, feedback_submitted=True, feedback_seen=False).all()

    return render_template("student/dashboard.html", username=username,
                           teacher_sections=teacher_sections,
                           new_feedback=new_feedback)


# ------------------------------------------------------------------ TEACHER DASHBOARD
@app.route("/teacher/dashboard")
def teacher_dashboard():
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("dashboard"))

    # Use StudentClass (correct enrollment table, not legacy class_id)
    enrollments  = StudentClass.query.filter_by(pin=teacher.teacher_pin).all()
    student_data = []
    for e in enrollments:
        s = User.query.filter_by(username=e.username, role="student").first()
        if not s: continue
        total     = Assignment.query.filter_by(username=s.username, assigned_by=username).count()
        submitted = Assignment.query.filter_by(username=s.username, assigned_by=username, submitted=True).count()
        student_data.append({"username": s.username, "total": total,
                              "submitted": submitted, "pending": total - submitted})
    new_pin = session.pop("new_pin", None)
    return render_template("teacher/dashboard.html", teacher=teacher,
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

    lib    = get_library()
    sfarim = list(lib.keys())            # ["Bereshit", "Shemot", ...]

    # Step 1 — teacher picks a sefer via GET ?sefer=
    selected_sefer = request.args.get("sefer") or request.form.get("sefer")
    parshiot       = list(lib[selected_sefer].keys()) if selected_sefer and selected_sefer in lib else []
    selected_parsha = request.form.get("parasha", "")

    error = None
    if request.method == "POST":
        title            = request.form.get("title", "").strip()
        parasha          = request.form.get("parasha", "").strip()
        aliyah           = request.form.get("aliyah", "").strip()
        due_date         = request.form.get("due_date", "").strip()
        notes            = request.form.get("notes", "").strip()
        recording_choice = request.form.get("recording_choice", "included")

        if not title or not parasha or not aliyah:
            error = "Please fill in all required fields."
        else:
            sefaria_ref, _ = build_sefaria_ref(parasha, aliyah)
            new_assignment = Assignment(
                username=student_username, title=title, parasha=parasha,
                aliyah=aliyah, due_date=due_date, assigned_by=username,
                notes=notes, sefaria_ref=sefaria_ref,
                recording_choice=recording_choice,
            )
            db.session.add(new_assignment)
            db.session.commit()
            if recording_choice == "own":
                return redirect(url_for("teacher_record_nusach", assignment_id=new_assignment.id))
            return redirect(url_for("teacher_dashboard"))

    existing = Assignment.query.filter_by(username=student_username).all()
    return render_template("teacher/assign.html",
        teacher         = teacher,
        student         = student,
        existing        = existing,
        error           = error,
        sfarim          = sfarim,
        selected_sefer  = selected_sefer,
        parshiot        = parshiot,
        selected_parsha = selected_parsha,
        aliyah_labels   = ASSIGN_ALIYAH_LABELS,
    )


# ------------------------------------------------------------------ SEFARIA PREVIEW API
@app.route("/api/sefaria-preview")
def sefaria_preview():
    parasha = request.args.get("parasha", "").strip()
    aliyah  = request.args.get("aliyah",  "").strip()
    if not parasha or not aliyah:
        return jsonify({"error": "Missing parasha or aliyah"}), 400
    ref = get_aliyah_ref(parasha, aliyah)
    if not ref:
        return jsonify({"error": "Parasha or aliyah not found in library"}), 404
    verses = get_verses_for_ref(ref)
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
    if not assignment.sefaria_ref:
        return redirect(url_for("dashboard"))

    verses = get_verses(assignment.parasha, assignment.aliyah,
                        fallback_ref=assignment.sefaria_ref)

    return render_template("student/parasha.html",
        name       = assignment.title,
        ref        = assignment.sefaria_ref,
        verses     = verses,
        assignment = assignment,
    )


# ------------------------------------------------------------------ TEACHER: VIEW STUDENT'S ASSIGNMENTS
@app.route("/teacher/student/<student_username>")
def teacher_student_view(student_username):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("dashboard"))
    student = User.query.filter_by(username=student_username, role="student").first()
    if not student: return redirect(url_for("teacher_dashboard"))

    submitted = Assignment.query.filter_by(username=student_username, assigned_by=username, submitted=True).all()
    assigned  = Assignment.query.filter_by(username=student_username, assigned_by=username, submitted=False).all()

    return render_template("teacher/student_view.html",
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
    if not assignment.sefaria_ref:
        return redirect(url_for("teacher_student_view", student_username=assignment.username))

    verses = get_verses(assignment.parasha, assignment.aliyah,
                        fallback_ref=assignment.sefaria_ref)

    return render_template("teacher/preview.html",
        assignment = assignment,
        name       = assignment.title,
        ref        = assignment.sefaria_ref,
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
    if not assignment.submitted or not assignment.recording_filename:
        return redirect(url_for("teacher_student_view", student_username=assignment.username))
    if not assignment.sefaria_ref:
        return redirect(url_for("teacher_student_view", student_username=assignment.username))

    verses = get_verses(assignment.parasha, assignment.aliyah,
                        fallback_ref=assignment.sefaria_ref)

    return render_template("teacher/review.html",
        assignment = assignment,
        name       = assignment.title,
        ref        = assignment.sefaria_ref,
        verses     = verses,
    )


# ------------------------------------------------------------------ TEACHER: SAVE GRADES (DRAFT)
@app.route("/teacher/save-grades/<int:assignment_id>", methods=["POST"])
def save_grades(assignment_id):
    username = session.get("username")
    if not username: return jsonify({"error": "Not logged in"}), 401
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return jsonify({"error": "Not authorized"}), 403
    assignment = Assignment.query.get(assignment_id)
    if not assignment: return jsonify({"error": "Not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    grades = data.get("grades", {})
    assignment.verse_grades  = _json.dumps(grades) if isinstance(grades, dict) else grades
    assignment.feedback_note = data.get("feedback_note", assignment.feedback_note or "")
    db.session.commit()
    return jsonify({"success": True})


# ------------------------------------------------------------------ TEACHER: SUBMIT FEEDBACK (FINALISE)
@app.route("/teacher/submit-feedback/<int:assignment_id>", methods=["POST"])
def submit_feedback(assignment_id):
    username = session.get("username")
    if not username: return jsonify({"error": "Not logged in"}), 401
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return jsonify({"error": "Not authorized"}), 403
    assignment = Assignment.query.get(assignment_id)
    if not assignment: return jsonify({"error": "Not found"}), 404

    data   = request.get_json(force=True, silent=True) or {}
    grades = data.get("grades", {})
    assignment.verse_grades          = _json.dumps(grades) if isinstance(grades, dict) else grades
    assignment.feedback_note         = data.get("feedback_note", "")
    assignment.feedback_submitted    = True
    assignment.feedback_seen         = False
    assignment.feedback_submitted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})


# ------------------------------------------------------------------ STUDENT: VIEW FEEDBACK
@app.route("/feedback/<int:assignment_id>")
def view_feedback(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.username != username:
        return redirect(url_for("dashboard"))
    if not assignment.feedback_seen:
        assignment.feedback_seen = True
        db.session.commit()

    grades = {}
    if assignment.verse_grades:
        try: grades = _json.loads(assignment.verse_grades)
        except: grades = {}

    verses = get_verses(assignment.parasha, assignment.aliyah,
                        fallback_ref=assignment.sefaria_ref)

    return render_template("student/feedback_view.html",
        assignment = assignment,
        grades     = grades,
        verses     = verses,
    )


# ------------------------------------------------------------------ STUDENT: MARK ALL FEEDBACK SEEN
@app.route("/mark-feedback-seen", methods=["GET","POST"])
def mark_feedback_seen():
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    Assignment.query.filter_by(username=username, feedback_submitted=True, feedback_seen=False)\
        .update({"feedback_seen": True})
    db.session.commit()
    if request.is_json:
        return jsonify({"success": True})
    return redirect(url_for("dashboard"))


# ------------------------------------------------------------------ TEACHER: RECORD NUSACH
@app.route("/teacher/record-nusach/<int:assignment_id>")
def teacher_record_nusach(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    teacher = User.query.filter_by(username=username, role="teacher").first()
    if not teacher: return redirect(url_for("dashboard"))
    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.assigned_by != username:
        return redirect(url_for("teacher_dashboard"))

    verses = get_verses(assignment.parasha, assignment.aliyah,
                        fallback_ref=assignment.sefaria_ref)

    return render_template("teacher/record_nusach.html",
        assignment = assignment,
        name       = assignment.title,
        ref        = assignment.sefaria_ref or assignment.parasha,
        verses     = verses,
    )


# ------------------------------------------------------------------ TEACHER: UPLOAD NUSACH RECORDING
@app.route("/upload-nusach/<int:assignment_id>", methods=["POST"])
def upload_nusach(assignment_id):
    username = session.get("username")
    if not username: return jsonify({"error": "Not logged in"}), 401
    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.assigned_by != username:
        return jsonify({"error": "Not authorized"}), 403
    if "recording" not in request.files:
        return jsonify({"error": "No file received"}), 400
    file = request.files["recording"]
    if not file or file.filename == "":
        return jsonify({"error": "Empty file"}), 400
    filename = f"teacher_{assignment_id}_{secure_filename(username)}.webm"
    file.save(os.path.join(app.config["RECORDING_FOLDER"], filename))
    assignment.teacher_recording_filename = filename
    db.session.commit()
    return jsonify({"success": True, "filename": filename})


# ------------------------------------------------------------------ STUDENT: UPLOAD RECORDING
@app.route("/upload-recording/<int:assignment_id>", methods=["POST"])
def upload_recording(assignment_id):
    username = session.get("username")
    if not username: return jsonify({"error": "Not logged in"}), 401
    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.username != username:
        return jsonify({"error": "Not authorized"}), 403
    if "recording" not in request.files:
        return jsonify({"error": "No file received"}), 400
    file = request.files["recording"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400
    filename = f"assignment_{assignment_id}_{secure_filename(username)}.webm"
    file.save(os.path.join(app.config["RECORDING_FOLDER"], filename))
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
    return render_template("student/edit_assignment.html", assignment=a, username=username)

@app.route("/congratulations/<int:assignment_id>")
def congratulations(assignment_id):
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    a = Assignment.query.get(assignment_id)
    return render_template("student/congratulations.html", username=username, assignment=a)

@app.route("/resources")
def resources():
    username = session.get("username")
    if not username: return redirect(url_for("home"))
    return render_template("student/resources.html", username=username)


if __name__ == "__main__":
    app.run(debug=True)