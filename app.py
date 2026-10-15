from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_from_directory, abort
)
import sqlite3
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "smart_college_secret_change_this"
)

DATABASE = os.environ.get("DATABASE_PATH", "database.db")

# ==============================
# PHOTO UPLOAD SETTINGS
# ==============================

UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_PHOTO_SIZE = 5 * 1024 * 1024  # Oru photo-ku 5 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Ella files-um serthu maximum 30 MB
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024


# ==============================
# DATABASE CONNECTION
# ==============================

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ==============================
# DATABASE TABLES
# ==============================

def init_db():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            department TEXT NOT NULL,
            phone TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL UNIQUE,
            student_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (complaint_id)
                REFERENCES complaints(id),
            FOREIGN KEY (student_id)
                REFERENCES students(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS complaint_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (complaint_id)
                REFERENCES complaints(id)
                ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ==============================
# COMMON HELPERS
# ==============================

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def save_complaint_photos(files, complaint_id, conn):
    """Valid photos-ai save panni database-la record seyyum."""

    for photo in files:
        if not photo or not photo.filename:
            continue

        original_name = secure_filename(photo.filename)

        if not original_name or not allowed_file(original_name):
            raise ValueError(
                "JPG, JPEG, PNG, WEBP photos mattum upload pannunga."
            )

        photo_data = photo.read()

        if not photo_data:
            continue

        if len(photo_data) > MAX_PHOTO_SIZE:
            raise ValueError("Oru photo maximum 5 MB irukkanum.")

        extension = original_name.rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{extension}"
        file_path = os.path.join(UPLOAD_FOLDER, filename)

        with open(file_path, "wb") as output:
            output.write(photo_data)

        conn.execute("""
            INSERT INTO complaint_photos
                (complaint_id, filename, original_name)
            VALUES (?, ?, ?)
        """, (complaint_id, filename, original_name))


def get_all_complaints():
    conn = get_db_connection()

    complaints = conn.execute("""
        SELECT
            c.id, c.student_id, c.subject, c.description,
            c.category, c.status, c.created_at,
            s.name, s.email, s.department, s.phone,
            f.rating AS feedback_rating,
            f.message AS feedback_message,
            f.created_at AS feedback_created_at
        FROM complaints c
        JOIN students s ON c.student_id = s.id
        LEFT JOIN feedback f ON c.id = f.complaint_id
        ORDER BY c.id DESC
    """).fetchall()

    result = []

    for complaint in complaints:
        item = dict(complaint)

        item["photos"] = conn.execute("""
            SELECT id, filename, original_name
            FROM complaint_photos
            WHERE complaint_id = ?
            ORDER BY id
        """, (complaint["id"],)).fetchall()

        result.append(item)

    conn.close()
    return result


# ==============================
# HOME
# ==============================

@app.route("/")
def home():
    return render_template("index.html")


# ==============================
# STUDENT REGISTER
# ==============================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        department = request.form.get("department", "").strip()
        phone = request.form.get("phone", "").strip()

        if not all([name, email, password, department, phone]):
            return "Ella fields-aiyum fill pannunga.", 400

        conn = get_db_connection()

        try:
            conn.execute("""
                INSERT INTO students
                    (name, email, password, department, phone)
                VALUES (?, ?, ?, ?, ?)
            """, (name, email, password, department, phone))

            conn.commit()

        except sqlite3.IntegrityError:
            return "Indha email already register aagiyirukku.", 400

        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


# ==============================
# STUDENT LOGIN
# ==============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()

        student = conn.execute("""
            SELECT *
            FROM students
            WHERE email = ? AND password = ?
        """, (email, password)).fetchone()

        conn.close()

        if student:
            session.clear()
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]
            session["student_email"] = student["email"]

            return redirect(url_for("dashboard"))

        return "Invalid Email or Password", 401

    return render_template("login.html")


# ==============================
# STUDENT DASHBOARD
# ==============================

@app.route("/dashboard")
@app.route("/student-dashboard")
def dashboard():
    if "student_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        name=session["student_name"]
    )


# ==============================
# SUBMIT COMPLAINT + PHOTOS
# ==============================

@app.route("/complaint", methods=["GET", "POST"])
def complaint():
    if "student_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()

        if not all([subject, description, category]):
            return "Ella complaint details-aiyum fill pannunga.", 400

        photos = request.files.getlist("photos")

        # Mudhalil files-ai validate pannuvom.
        total_size = 0

        for photo in photos:
            if not photo or not photo.filename:
                continue

            safe_name = secure_filename(photo.filename)

            if not safe_name or not allowed_file(safe_name):
                return "JPG, JPEG, PNG, WEBP photos mattum allowed.", 400

            data = photo.read()
            total_size += len(data)
            photo.seek(0)

            if len(data) > MAX_PHOTO_SIZE:
                return "Oru photo maximum 5 MB irukkanum.", 400

        if total_size > 30 * 1024 * 1024:
            return "Total photo size 30 MB-ai vida adhigama irukka koodadhu.", 400

        conn = get_db_connection()

        try:
            cursor = conn.execute("""
                INSERT INTO complaints
                    (student_id, subject, description, category)
                VALUES (?, ?, ?, ?)
            """, (
                session["student_id"],
                subject,
                description,
                category
            ))

            complaint_id = cursor.lastrowid

            save_complaint_photos(
                photos,
                complaint_id,
                conn
            )

            conn.commit()

        except (ValueError, OSError) as error:
            conn.rollback()
            return str(error), 400

        finally:
            conn.close()

        return redirect(url_for("my_complaints"))

    return render_template("complaint.html")


# ==============================
# MY COMPLAINTS
# ==============================

@app.route("/my_complaints")
def my_complaints():
    if "student_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    complaints = conn.execute("""
        SELECT
            c.*,
            f.rating AS feedback_rating,
            f.message AS feedback_message,
            f.created_at AS feedback_created_at
        FROM complaints c
        LEFT JOIN feedback f ON f.complaint_id = c.id
        WHERE c.student_id = ?
        ORDER BY c.id DESC
    """, (session["student_id"],)).fetchall()

    result = []

    for complaint_row in complaints:
        item = dict(complaint_row)

        item["photos"] = conn.execute("""
            SELECT id, filename, original_name
            FROM complaint_photos
            WHERE complaint_id = ?
            ORDER BY id
        """, (complaint_row["id"],)).fetchall()

        result.append(item)

    conn.close()

    return render_template(
        "my_complaints.html",
        complaints=result
    )


# ==============================
# SECURE PHOTO VIEW
# ==============================

@app.route("/complaint_photo/<int:photo_id>")
def complaint_photo(photo_id):
    student_id = session.get("student_id")
    is_admin = session.get("admin_logged_in")
    is_staff = session.get("staff_logged_in")

    if not (student_id or is_admin or is_staff):
        return redirect(url_for("login"))

    conn = get_db_connection()

    photo = conn.execute("""
        SELECT p.filename, c.student_id
        FROM complaint_photos p
        JOIN complaints c ON c.id = p.complaint_id
        WHERE p.id = ?
    """, (photo_id,)).fetchone()

    conn.close()

    if photo is None:
        abort(404)

    # Student than submit panna complaint photo mattum paarkkalaam.
    if student_id and photo["student_id"] != student_id:
        if not (is_admin or is_staff):
            abort(403)

    return send_from_directory(
        UPLOAD_FOLDER,
        photo["filename"],
        as_attachment=False
    )


# ==============================
# STUDENT FEEDBACK
# ==============================

@app.route("/feedback/<int:complaint_id>", methods=["POST"])
def submit_feedback(complaint_id):
    if "student_id" not in session:
        return redirect(url_for("login"))

    rating = request.form.get("rating", type=int)
    message = request.form.get("message", "").strip()
    student_id = session["student_id"]

    if rating not in (1, 2, 3, 4, 5) or not message:
        return "Rating select panni feedback enter pannunga.", 400

    conn = get_db_connection()

    try:
        complaint_row = conn.execute("""
            SELECT id, status
            FROM complaints
            WHERE id = ? AND student_id = ?
        """, (complaint_id, student_id)).fetchone()

        if complaint_row is None:
            return "Complaint not found.", 404

        if complaint_row["status"] != "Resolved":
            return "Resolved complaint-ku mattum feedback submit pannalaam.", 400

        conn.execute("""
            INSERT INTO feedback
                (complaint_id, student_id, rating, message)
            VALUES (?, ?, ?, ?)
        """, (complaint_id, student_id, rating, message))

        conn.commit()
        return redirect(url_for("my_complaints"))

    except sqlite3.IntegrityError:
        return "Feedback already submit panniyachu.", 400

    finally:
        conn.close()


# ==============================
# STUDENT LOGOUT
# ==============================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ==============================
# ADMIN LOGIN DETAILS
# ==============================

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "College123")


# ==============================
# ADMIN LOGIN
# ==============================

@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))

        return "Invalid Admin Username or Password", 401

    return render_template("admin_login.html")


# ==============================
# ADMIN DASHBOARD
# ==============================

@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    return render_template(
        "admin.html",
        complaints=get_all_complaints()
    )


# ==============================
# ADMIN UPDATE STATUS
# ==============================

@app.route("/update_status/<int:complaint_id>", methods=["POST"])
def update_status(complaint_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    return update_complaint_status(
        complaint_id,
        "admin"
    )


# ==============================
# COMMON STATUS UPDATE
# ==============================

def update_complaint_status(complaint_id, redirect_page):
    status = request.form.get("status")

    allowed_status = [
        "Pending",
        "In Progress",
        "Resolved",
        "Rejected"
    ]

    if status not in allowed_status:
        return "Invalid Status", 400

    conn = get_db_connection()

    cursor = conn.execute("""
        UPDATE complaints
        SET status = ?
        WHERE id = ?
    """, (status, complaint_id))

    conn.commit()
    updated = cursor.rowcount
    conn.close()

    if updated == 0:
        abort(404)

    return redirect(url_for(redirect_page))


# ==============================
# ADMIN LOGOUT
# ==============================

@app.route("/admin_logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


# ==============================
# STAFF LOGIN DETAILS
# ==============================

STAFF_USERNAME = os.environ.get("STAFF_USERNAME", "staff")
STAFF_PASSWORD = os.environ.get("STAFF_PASSWORD", "Staff123")


# ==============================
# STAFF LOGIN
# ==============================

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == STAFF_USERNAME and password == STAFF_PASSWORD:
            session.clear()
            session["staff_logged_in"] = True
            return redirect(url_for("staff_dashboard"))

        return "Invalid Staff Username or Password", 401

    return render_template("staff_login.html")


# ==============================
# STAFF DASHBOARD
# ==============================

@app.route("/staff_dashboard")
def staff_dashboard():
    if not session.get("staff_logged_in"):
        return redirect(url_for("staff_login"))

    return render_template(
        "staff.html",
        complaints=get_all_complaints()
    )


# ==============================
# STAFF UPDATE STATUS
# ==============================

@app.route(
    "/staff_update_status/<int:complaint_id>",
    methods=["POST"]
)
def staff_update_status(complaint_id):
    if not session.get("staff_logged_in"):
        return redirect(url_for("staff_login"))

    return update_complaint_status(
        complaint_id,
        "staff_dashboard"
    )


# ==============================
# STAFF LOGOUT
# ==============================

@app.route("/staff_logout")
def staff_logout():
    session.pop("staff_logged_in", None)
    return redirect(url_for("staff_login"))


# ==============================
# FILE SIZE ERROR HANDLER
# ==============================

@app.errorhandler(413)
def file_too_large(error):
    return "Upload size 30 MB-ai thaanda koodadhu.", 413


# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    app.run(debug=True)
