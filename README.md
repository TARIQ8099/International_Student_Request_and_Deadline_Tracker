# International Student Request & Deadline Tracker

Prototype for the Software Project Management semester project, Zhengzhou University.

Developer: MD Tariq Uz Zaman

## Team

| Member | Role | Responsibilities |
| --- | --- | --- |
| MD Eaftekhirul Islam ([@eafte](https://github.com/eafte)) | Project Manager | Schedule, WBS, weekly meetings, progress and risks |
| MD Tariq Uz Zaman ([@TARIQ8099](https://github.com/TARIQ8099)) | Business Analyst and Developer | Requirements and the code of this app |
| MD Abir Ahmmed | Design and Documentation Lead | UML diagrams, mock-ups, report and slides |

## What it does

- Students log in, submit requests to the School of International Education (SIE) and follow their status.
  Request types: residence permit renewal, study certificate, leave or travel approval.
- SIE staff see all requests on one dashboard, filter them by type and status, change the status
  (Submitted, In review, Approved, Rejected, Ready for pickup) and leave a comment for the student.
- SIE staff add new students on the Students page (full name, username, starting password and an
  optional permit expiry date) and see every student's permit date and number of requests.
- When a student finishes their studies, staff click "Mark as graduated". The student can no longer log in
  and leaves the active lists, dashboard counts and permit warnings, but their old requests stay in the
  records (Dashboard, Students filter: Graduated). "Restore" reopens the account if needed.
- Every user can change their password, so students replace the starting password after their first login.
- Students save their residence permit expiry date. From 60 days before expiry, the student sees a
  warning with the extension deadline, and the student appears on the staff dashboard. The deadline is
  30 days before expiry (Exit and Entry Administration Law of the PRC, Article 32).

All data is made up. The app does not connect to any university system.

## Run it on Windows

Open PowerShell in this folder and run:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Then open http://127.0.0.1:5000 in a browser. Stop the server with Ctrl+C.

The first run creates `tracker.db` with sample data. Delete `tracker.db` to start again with fresh sample data.
An older `tracker.db` is upgraded automatically when the app starts, so its data is kept.

## Sample accounts

All sample accounts use the password `demo1234`.

| Username | Role | Residence permit |
| --- | --- | --- |
| staff | SIE office staff | - |
| amina | Student | expires in 25 days (extension deadline already passed) |
| carlos | Student | expires in 50 days (warning shown) |
| sara | Student | expires in 200 days (no warning) |

## Tests

```
.venv\Scripts\python -m pytest
```

## Files

| File | Purpose |
| --- | --- |
| app.py | Pages, login, database and permit reminder logic |
| schema.sql | Database tables |
| templates/ | HTML pages |
| static/style.css | Page styling |
| static/fonts/ | Fonts used by the pages, with their licences |
| templates/_icons.html | Icon set used by the pages |
| tests/test_app.py | Automated tests |

## Tools

Python, Flask and SQLite. Fonts: Lexend and Source Sans 3 (SIL Open Font License). Icons: Phosphor Icons
(MIT License). The fonts and icons are stored in the project, so the app also works without internet.
All tools are free and open source, so the project costs 0 yuan.
