from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
import os
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random, string, re, requests
from html import unescape
import sefaria as sf

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
# All Sefaria logic lives in sefaria.py.
# These thin wrappers keep the rest of app.py unchanged.

ALIYAH_INDEX = {
    "First Aliyah": 0, "Second Aliyah": 1, "Third Aliyah": 2,
    "Fourth Aliyah": 3, "Fifth Aliyah": 4, "Sixth Aliyah": 5,
    "Seventh Aliyah": 6, "Maftir": 7, "Haftorah": None,
}

def get_section_data(ref, aliyot_refs=None):
    """Fetch verses for a ref. Returns (verses, []) — aliyot unused now."""
    return sf.get_verses_for_ref(ref), []

def fetch_parasha_aliyot(parasha_name):
    """Return the list of aliyah refs for a parasha from the library."""
    return sf.get_aliyot_for_parasha(parasha_name)

def build_sefaria_ref(parasha, aliyah_label):
    """Resolve a parasha + aliyah label to a Sefaria ref."""
    ref = sf.get_aliyah_ref(parasha, aliyah_label)
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
    parasha_list = sf.get_parasha_list()
    return render_template("assign.html", teacher=teacher, student=student,
                           existing=existing, error=error,
                           parasha_list=parasha_list)

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