import re
import sqlite3
from datetime import date

import pytest

import app as tracker


@pytest.fixture
def client(tmp_path):
    tracker.app.config.update(DATABASE=str(tmp_path / "test.db"), TESTING=True)
    with tracker.app.app_context():
        tracker.init_db()
    with tracker.app.test_client() as test_client:
        yield test_client


def csrf_token(client, path):
    page = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def login(client, username, password=tracker.DEMO_PASSWORD):
    data = {"username": username, "password": password, "csrf_token": csrf_token(client, "/login")}
    return client.post("/login", data=data, follow_redirects=True)


def request_row(request_id):
    with tracker.app.app_context():
        return tracker.get_db().execute(
            "SELECT status, staff_comment FROM requests WHERE id = ?", (request_id,)).fetchone()


def test_reminder_text_follows_the_60_and_30_day_rules():
    today = date(2026, 10, 24)
    assert tracker.reminder_text(None, today) is None
    assert tracker.reminder_text("2027-03-01", today) is None                   # more than 60 days left
    assert "Apply for an extension by 2026-11-23" in tracker.reminder_text("2026-12-23", today)  # exactly 60
    assert "by 2026-10-24" in tracker.reminder_text("2026-11-23", today)        # 30 days left: deadline is today
    assert "has passed" in tracker.reminder_text("2026-11-22", today)           # 29 days left
    assert "expired on 2026-10-01" in tracker.reminder_text("2026-10-01", today)


def test_wrong_password_is_rejected(client):
    page = login(client, "amina", "not-the-password").get_data(as_text=True)
    assert "Wrong username or password" in page


def test_student_submits_a_request_and_sees_it(client):
    login(client, "carlos")
    data = {"type": "Study certificate", "note": "For my bank account",
            "csrf_token": csrf_token(client, "/student/requests/new")}
    client.post("/student/requests/new", data=data)
    page = client.get("/student").get_data(as_text=True)
    assert "For my bank account" in page
    assert "Submitted" in page


def test_student_cannot_open_staff_pages(client):
    login(client, "amina")
    assert client.get("/staff").status_code == 403
    assert client.get("/staff/requests/1").status_code == 403


def test_staff_updates_status_and_comment(client):
    login(client, "staff")
    data = {"status": "Approved", "staff_comment": "Approved, collect on Friday.",
            "csrf_token": csrf_token(client, "/staff/requests/1")}
    client.post("/staff/requests/1", data=data)
    row = request_row(1)
    assert (row["status"], row["staff_comment"]) == ("Approved", "Approved, collect on Friday.")


def test_invalid_status_is_not_saved(client):
    login(client, "staff")
    data = {"status": "Lost", "staff_comment": "", "csrf_token": csrf_token(client, "/staff/requests/1")}
    client.post("/staff/requests/1", data=data)
    assert request_row(1)["status"] == "In review"


def test_dashboard_lists_only_permits_within_60_days(client):
    login(client, "staff")
    page = client.get("/staff").get_data(as_text=True)
    assert "Amina Yusuf" in page and "Carlos Mendes" in page   # 25 and 50 days left
    expiring_section = page.split("All requests")[0]
    assert "Sara Ahmed" not in expiring_section                # 200 days left


def add_student(client, **fields):
    data = {"full_name": "Lina Park", "username": "lina", "password": "welcome123", "permit_expiry": "2027-09-01"}
    data.update(fields, csrf_token=csrf_token(client, "/staff/students"))
    return client.post("/staff/students", data=data, follow_redirects=True).get_data(as_text=True)


def student_count():
    with tracker.app.app_context():
        return tracker.get_db().execute("SELECT COUNT(*) FROM users WHERE role = 'student'").fetchone()[0]


def test_staff_adds_a_student_who_can_then_log_in(client):
    login(client, "staff")
    assert "Lina Park was added" in add_student(client)
    client.get("/logout")
    assert "Welcome, Lina" in login(client, "lina", "welcome123").get_data(as_text=True)


def test_invalid_new_students_are_refused(client):
    login(client, "staff")
    assert "already taken" in add_student(client, username="amina")
    assert "8 to 128 characters" in add_student(client, username="newone", password="short")
    assert "Usernames need" in add_student(client, username="Bad Name!")
    assert student_count() == 3


def test_students_cannot_open_the_students_page(client):
    login(client, "amina")
    assert client.get("/staff/students").status_code == 403


def test_student_changes_password(client):
    login(client, "carlos")

    def change(current, new, repeat):
        data = {"current_password": current, "new_password": new, "confirm_password": repeat,
                "csrf_token": csrf_token(client, "/account/password")}
        return client.post("/account/password", data=data, follow_redirects=True).get_data(as_text=True)

    assert "not correct" in change("not-the-password", "newpass123", "newpass123")
    assert "do not match" in change(tracker.DEMO_PASSWORD, "newpass123", "different123")
    assert "was changed" in change(tracker.DEMO_PASSWORD, "newpass123", "newpass123")
    client.get("/logout")
    assert "Wrong username or password" in login(client, "carlos").get_data(as_text=True)
    assert "Welcome, Carlos" in login(client, "carlos", "newpass123").get_data(as_text=True)


def test_form_without_csrf_token_is_refused(client):
    response = client.post("/login", data={"username": "amina", "password": tracker.DEMO_PASSWORD})
    assert response.status_code == 400


def student_id(username):
    with tracker.app.app_context():
        return tracker.get_db().execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]


def staff_post(client, path):
    data = {"csrf_token": csrf_token(client, "/staff/students")}
    return client.post(path, data=data, follow_redirects=True).get_data(as_text=True)


def test_graduated_student_cannot_log_in_until_restored(client):
    login(client, "staff")
    assert "marked as graduated" in staff_post(client, f"/staff/students/{student_id('carlos')}/graduate")
    client.get("/logout")
    assert "has graduated" in login(client, "carlos").get_data(as_text=True)

    login(client, "staff")
    assert "was restored" in staff_post(client, f"/staff/students/{student_id('carlos')}/restore")
    client.get("/logout")
    assert "Welcome, Carlos" in login(client, "carlos").get_data(as_text=True)


def test_graduation_ends_a_student_session_that_is_already_open(client):
    login(client, "carlos")
    with tracker.app.test_client() as staff:
        login(staff, "staff")
        staff_post(staff, f"/staff/students/{student_id('carlos')}/graduate")
    assert "has graduated" in client.get("/student", follow_redirects=True).get_data(as_text=True)


def test_graduates_leave_active_lists_but_keep_their_requests(client):
    login(client, "staff")
    staff_post(client, f"/staff/students/{student_id('amina')}/graduate")

    dashboard = client.get("/staff").get_data(as_text=True)
    assert "Amina Yusuf" not in dashboard            # no permit warning, no rows among current requests
    history = client.get("/staff?who=graduated").get_data(as_text=True)
    assert "Residence permit renewal" in history and "Graduated" in history

    students_page = client.get("/staff/students").get_data(as_text=True)
    current_part, graduated_part = students_page.split("Graduated students</h2>")
    assert "Amina Yusuf" not in current_part
    assert "Amina Yusuf" in graduated_part


def test_old_database_gets_the_graduated_column(tmp_path):
    old_db = tmp_path / "old.db"
    with sqlite3.connect(old_db) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, "
                   "full_name TEXT, role TEXT, permit_expiry TEXT)")
    tracker.app.config.update(DATABASE=str(old_db))
    with tracker.app.app_context():
        tracker.upgrade_db()
        columns = {row["name"] for row in tracker.get_db().execute("PRAGMA table_info(users)")}
    assert "graduated_on" in columns
