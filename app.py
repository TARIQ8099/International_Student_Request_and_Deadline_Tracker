"""International Student Request & Deadline Tracker.

A small web portal for the School of International Education (SIE). Students submit
requests and follow their status, staff manage all requests from one dashboard, and
both see a warning when a residence permit is close to expiry.
"""
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
REQUEST_TYPES = ["Residence permit renewal", "Study certificate", "Leave or travel approval"]
STATUSES = ["Submitted", "In review", "Approved", "Rejected", "Ready for pickup"]
STATUS_ICONS = {"Submitted": "paper-plane-tilt", "In review": "hourglass-medium", "Approved": "check-circle",
                "Rejected": "x-circle", "Ready for pickup": "package"}
STUDENT_GROUPS = {"current": "u.graduated_on IS NULL", "graduated": "u.graduated_on IS NOT NULL", "all": "1 = 1"}
REMINDER_DAYS = 60       # warn early enough to meet the legal deadline below
APPLY_BEFORE_DAYS = 30   # Exit and Entry Administration Law, Article 32
MAX_TEXT = 500
MIN_PASSWORD, MAX_PASSWORD = 8, 128
USERNAME_PATTERN = re.compile(r"[a-z0-9._-]{3,30}")
DEMO_PASSWORD = "demo1234"  # sample accounts only, see README
CLOSED_ACCOUNT = "This account is closed because the student has graduated. Please contact the SIE office."

app = Flask(__name__)
app.config.update(
    DATABASE=os.environ.get("TRACKER_DB", str(BASE_DIR / "tracker.db")),
    # shortcut: a random key logs everyone out when the server restarts; set SECRET_KEY before real use
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(16),
)
app.jinja_env.globals.update(reminder_days=REMINDER_DAYS, apply_before_days=APPLY_BEFORE_DAYS,
                             min_password=MIN_PASSWORD, max_password=MAX_PASSWORD)


# ---------- page helpers ----------

@app.template_global()
def icon(name):
    """Icon from templates/_icons.html; decorative, so screen readers skip it."""
    return Markup(f'<svg class="icon" aria-hidden="true" focusable="false"><use href="#i-{name}"></use></svg>')


@app.template_global()
def status_pill(status):
    css = escape(status.lower().replace(" ", "-"))
    return Markup(f'<span class="pill pill-{css}">{icon(STATUS_ICONS.get(status, "clock"))}{escape(status)}</span>')


# ---------- database ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now():
    return datetime.now().isoformat(sep=" ", timespec="minutes")


def init_db():
    """Create the tables and fill them with made-up sample data."""
    db = get_db()
    db.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8"))

    today = date.today()
    users = [
        # username, full name, role, days until the permit expires (None for staff)
        ("staff", "Zhang Lin", "staff", None),
        ("amina", "Amina Yusuf", "student", 25),
        ("carlos", "Carlos Mendes", "student", 50),
        ("sara", "Sara Ahmed", "student", 200),
    ]
    for username, full_name, role, days in users:
        expiry = (today + timedelta(days=days)).isoformat() if days is not None else None
        db.execute(
            "INSERT INTO users (username, password_hash, full_name, role, permit_expiry) VALUES (?, ?, ?, ?, ?)",
            (username, generate_password_hash(DEMO_PASSWORD), full_name, role, expiry),
        )

    ids = {row["username"]: row["id"] for row in db.execute("SELECT id, username FROM users")}
    samples = [
        ("amina", "Residence permit renewal", "My permit expires next month.", "In review",
         "Please bring your passport and two photos."),
        ("amina", "Study certificate", "Needed for my bank account.", "Ready for pickup",
         "Collect it from the SIE office."),
        ("carlos", "Leave or travel approval", "Travelling home from 20 to 28 December.", "Submitted", ""),
        ("sara", "Study certificate", "For a scholarship application.", "Rejected",
         "Duplicate request: your certificate was issued last week."),
    ]
    for username, req_type, note, status, comment in samples:
        db.execute(
            "INSERT INTO requests (student_id, type, note, status, staff_comment, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ids[username], req_type, note, status, comment, now(), now()),
        )
    db.commit()


def upgrade_db():
    """Add columns that newer versions need, so an older tracker.db keeps its data."""
    db = get_db()
    columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    if "graduated_on" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN graduated_on TEXT")
        db.commit()


# ---------- permit reminders ----------

@app.template_global()
def days_left(expiry, today=None):
    """Days until a permit expires (negative once expired), or None if no date is saved."""
    if not expiry:
        return None
    return (date.fromisoformat(expiry) - (today or date.today())).days


def reminder_text(expiry, today=None):
    """Warning for the student, or None while the permit is not close to expiry."""
    days = days_left(expiry, today)
    if days is None or days > REMINDER_DAYS:
        return None
    if days < 0:
        return f"Your residence permit expired on {expiry}. Contact the SIE office today."
    deadline = date.fromisoformat(expiry) - timedelta(days=APPLY_BEFORE_DAYS)
    if days < APPLY_BEFORE_DAYS:
        return (f"Your residence permit expires on {expiry}. The extension deadline ({deadline}) "
                "has passed, so contact the SIE office today.")
    return f"Your residence permit expires on {expiry}. Apply for an extension by {deadline}."


# ---------- login and security ----------

def login_required(role=None):
    """Only logged-in users (with this role, if one is given) may open the page."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            user = get_db().execute("SELECT graduated_on FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            if user is None or user["graduated_on"]:  # graduated while logged in: end the session
                session.clear()
                flash(CLOSED_ACCOUNT, "error")
                return redirect(url_for("login"))
            if role and session["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.before_request
def check_csrf_token():
    """Every form carries a secret token, so other websites cannot submit forms for the user."""
    if request.method == "POST":
        expected = session.get("csrf_token")
        if not expected or not secrets.compare_digest(request.form.get("csrf_token", ""), expected):
            abort(400)


@app.context_processor
def add_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return {"csrf_token": session["csrf_token"]}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (request.form.get("username", "").strip().lower(),)
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            flash("Wrong username or password.", "error")
        elif user["graduated_on"]:
            flash(CLOSED_ACCOUNT, "error")
        else:
            session.clear()  # start a fresh session after login
            session.update(user_id=user["id"], role=user["role"], name=user["full_name"])
            return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("staff_dashboard" if session["role"] == "staff" else "student_home"))


@app.route("/account/password", methods=["GET", "POST"])
@login_required()
def change_password():
    if request.method == "POST":
        db = get_db()
        user = db.execute("SELECT password_hash FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        new_password = request.form.get("new_password", "")
        if not check_password_hash(user["password_hash"], request.form.get("current_password", "")):
            flash("Your current password is not correct.", "error")
        elif not MIN_PASSWORD <= len(new_password) <= MAX_PASSWORD:
            flash(f"The new password needs {MIN_PASSWORD} to {MAX_PASSWORD} characters.", "error")
        elif new_password != request.form.get("confirm_password", ""):
            flash("The two new passwords do not match.", "error")
        else:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(new_password), session["user_id"]))
            db.commit()
            flash("Your password was changed.", "success")
            return redirect(url_for("home"))
    return render_template("change_password.html")


# ---------- student pages ----------

@app.route("/student")
@login_required("student")
def student_home():
    db = get_db()
    me = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    my_requests = db.execute(
        "SELECT * FROM requests WHERE student_id = ? ORDER BY created_at DESC, id DESC", (me["id"],)
    ).fetchall()
    expiry = me["permit_expiry"]
    deadline = (date.fromisoformat(expiry) - timedelta(days=APPLY_BEFORE_DAYS)).isoformat() if expiry else None
    return render_template("student_home.html", me=me, requests=my_requests, alert=reminder_text(expiry),
                           days=days_left(expiry), deadline=deadline)


@app.post("/student/permit")
@login_required("student")
def update_permit():
    value = request.form.get("permit_expiry", "")
    try:
        date.fromisoformat(value)
    except ValueError:
        flash("Please enter a valid date.", "error")
    else:
        db = get_db()
        db.execute("UPDATE users SET permit_expiry = ? WHERE id = ?", (value, session["user_id"]))
        db.commit()
        flash("Permit expiry date saved.", "success")
    return redirect(url_for("student_home"))


@app.route("/student/requests/new", methods=["GET", "POST"])
@login_required("student")
def new_request():
    if request.method == "POST":
        req_type = request.form.get("type")
        note = request.form.get("note", "").strip()
        if req_type not in REQUEST_TYPES or len(note) > MAX_TEXT:
            flash(f"Please choose a request type and keep the note under {MAX_TEXT} characters.", "error")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO requests (student_id, type, note, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'Submitted', ?, ?)",
                (session["user_id"], req_type, note, now(), now()),
            )
            db.commit()
            flash("Request submitted.", "success")
            return redirect(url_for("student_home"))
    return render_template("new_request.html", types=REQUEST_TYPES)


# ---------- staff pages ----------

@app.route("/staff")
@login_required("staff")
def staff_dashboard():
    db = get_db()
    type_filter = request.args.get("type", "")
    status_filter = request.args.get("status", "")
    who = request.args.get("who", "current")
    if who not in STUDENT_GROUPS:
        who = "current"

    sql = ("SELECT r.*, u.full_name, u.graduated_on FROM requests r JOIN users u ON u.id = r.student_id "
           "WHERE " + STUDENT_GROUPS[who])
    params = []
    if type_filter in REQUEST_TYPES:
        sql += " AND r.type = ?"
        params.append(type_filter)
    if status_filter in STATUSES:
        sql += " AND r.status = ?"
        params.append(status_filter)
    all_requests = db.execute(sql + " ORDER BY r.created_at DESC, r.id DESC", params).fetchall()

    counts = {row[0]: row[1] for row in db.execute(
        "SELECT r.status, COUNT(*) FROM requests r JOIN users u ON u.id = r.student_id "
        "WHERE u.graduated_on IS NULL GROUP BY r.status")}

    expiring = []
    students = db.execute(
        "SELECT full_name, permit_expiry FROM users "
        "WHERE role = 'student' AND graduated_on IS NULL AND permit_expiry IS NOT NULL ORDER BY permit_expiry"
    )
    for student in students:
        days = days_left(student["permit_expiry"])
        if days <= REMINDER_DAYS:
            expiring.append({"name": student["full_name"], "expiry": student["permit_expiry"], "days": days})

    return render_template("staff_dashboard.html", requests=all_requests, expiring=expiring, counts=counts,
                           total=sum(counts.values()), types=REQUEST_TYPES, statuses=STATUSES,
                           type_filter=type_filter, status_filter=status_filter, who=who)


def new_student_error(db, form, password):
    """Why the new student cannot be saved, or None when the form is valid."""
    if not form["full_name"] or len(form["full_name"]) > 100:
        return "Please enter the student's full name (up to 100 characters)."
    if not USERNAME_PATTERN.fullmatch(form["username"]):
        return "Usernames need 3 to 30 characters: lowercase letters, numbers, dots, dashes or underscores."
    if db.execute("SELECT 1 FROM users WHERE username = ?", (form["username"],)).fetchone():
        return f"The username {form['username']} is already taken."
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return f"The starting password needs {MIN_PASSWORD} to {MAX_PASSWORD} characters."
    if form["permit_expiry"]:
        try:
            date.fromisoformat(form["permit_expiry"])
        except ValueError:
            return "Please enter a valid permit expiry date."
    return None


@app.route("/staff/students", methods=["GET", "POST"])
@login_required("staff")
def students():
    db = get_db()
    form = {}
    if request.method == "POST":
        form = {
            "full_name": request.form.get("full_name", "").strip(),
            "username": request.form.get("username", "").strip().lower(),
            "permit_expiry": request.form.get("permit_expiry", "").strip(),
        }
        password = request.form.get("password", "")
        error = new_student_error(db, form, password)
        if error:
            flash(error, "error")
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, role, permit_expiry) "
                "VALUES (?, ?, ?, 'student', ?)",
                (form["username"], generate_password_hash(password), form["full_name"], form["permit_expiry"] or None),
            )
            db.commit()
            flash(f"{form['full_name']} was added and can now log in as {form['username']}.", "success")
            return redirect(url_for("students"))

    all_students = db.execute(
        "SELECT u.id, u.full_name, u.username, u.permit_expiry, u.graduated_on, COUNT(r.id) AS request_count "
        "FROM users u LEFT JOIN requests r ON r.student_id = u.id "
        "WHERE u.role = 'student' GROUP BY u.id ORDER BY u.full_name"
    ).fetchall()
    return render_template("students.html", form=form,
                           current=[s for s in all_students if not s["graduated_on"]],
                           graduated=[s for s in all_students if s["graduated_on"]])


def set_graduated(student_id, graduated_on):
    """Close (graduated_on = a date) or reopen (None) a student's account; their requests are kept."""
    db = get_db()
    student = db.execute("SELECT full_name FROM users WHERE id = ? AND role = 'student'", (student_id,)).fetchone()
    if student is None:
        abort(404)
    db.execute("UPDATE users SET graduated_on = ? WHERE id = ?", (graduated_on, student_id))
    db.commit()
    if graduated_on:
        flash(f"{student['full_name']} was marked as graduated and can no longer log in.", "success")
    else:
        flash(f"{student['full_name']} was restored and can log in again.", "success")
    return redirect(url_for("students"))


@app.post("/staff/students/<int:student_id>/graduate")
@login_required("staff")
def graduate_student(student_id):
    return set_graduated(student_id, date.today().isoformat())


@app.post("/staff/students/<int:student_id>/restore")
@login_required("staff")
def restore_student(student_id):
    return set_graduated(student_id, None)


@app.route("/staff/requests/<int:request_id>", methods=["GET", "POST"])
@login_required("staff")
def manage_request(request_id):
    db = get_db()
    row = db.execute(
        "SELECT r.*, u.full_name, u.permit_expiry, u.graduated_on FROM requests r "
        "JOIN users u ON u.id = r.student_id WHERE r.id = ?", (request_id,)
    ).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        status = request.form.get("status")
        comment = request.form.get("staff_comment", "").strip()
        if status not in STATUSES or len(comment) > MAX_TEXT:
            flash(f"Please choose a valid status and keep the comment under {MAX_TEXT} characters.", "error")
        else:
            db.execute(
                "UPDATE requests SET status = ?, staff_comment = ?, updated_at = ? WHERE id = ?",
                (status, comment, now(), request_id),
            )
            db.commit()
            flash(f"Request #{request_id} updated.", "success")
            return redirect(url_for("staff_dashboard"))
    return render_template("manage_request.html", r=row, statuses=STATUSES)


if __name__ == "__main__":
    with app.app_context():
        if Path(app.config["DATABASE"]).exists():
            upgrade_db()
        else:
            init_db()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
