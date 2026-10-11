
import os
import sqlite3
import uuid
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "change-this-secret-before-real-use"
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


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
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    # Add photo column to an existing complaints table safely.
    columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(complaints)").fetchall()
    ]
    if "photo" not in columns:
        conn.execute("ALTER TABLE complaints ADD COLUMN photo TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    conn.commit()
    conn.close()


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def save_complaint_photo(file):
    if not file or not file.filename:
        return None

    if not allowed_file(file.filename):
        raise ValueError("Photo must be JPG, JPEG, PNG, or WEBP.")

    original_name = secure_filename(file.filename)
    extension = original_name.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{extension}"
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        department = request.form["department"].strip()
        phone = request.form["phone"].strip()

        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO students (name, email, password, department, phone)
                VALUES (?, ?, ?, ?, ?)
            """, (name, email, password, department, phone))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "Email already registered. Please use another email."
        conn.close()
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]

        conn = get_db_connection()
        student = conn.execute("""
            SELECT * FROM students WHERE email = ? AND password = ?
        """, (email, password)).fetchone()
        conn.close()

        if student:
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]
            session["student_email"] = student["email"]
            return redirect(url_for("dashboard"))

        return "Invalid Email or Password"

    return render_template("login.html")


@app.route("/dashboard")
@app.route("/student-dashboard")
def dashboard():
    if "student_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", name=session["student_name"])


@app.route("/complaint", methods=["GET", "POST"])
def complaint():
    if "student_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        subject = request.form["subject"].strip()
        description = request.form["description"].strip()
        category = request.form["category"].strip()
        photo_file = request.files.get("photo")

        try:
            photo = save_complaint_photo(photo_file)
        except ValueError as error:
            return str(error), 400

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO complaints
                (student_id, subject, description, category, photo)
            VALUES (?, ?, ?, ?, ?)
        """, (session["student_id"], subject, description, category, photo))
        conn.commit()
        conn.close()
        return redirect(url_for("my_complaints"))

    return render_template("complaint.html")


@app.route("/my_complaints")
def my_complaints():
    if "student_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    complaints = conn.execute("""
        SELECT * FROM complaints
        WHERE student_id = ?
        ORDER BY id DESC
    """, (session["student_id"],)).fetchall()
    conn.close()

    return render_template("my_complaints.html", complaints=complaints)


@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if "student_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        try:
            rating = int(request.form["rating"])
        except (ValueError, KeyError):
            return "Please select a rating from 1 to 5.", 400

        comment = request.form.get("comment", "").strip()
        if rating not in range(1, 6) or not comment:
            return "Please select a rating and enter a comment.", 400

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO feedback (student_id, rating, comment)
            VALUES (?, ?, ?)
        """, (session["student_id"], rating, comment))
        conn.commit()
        conn.close()

        flash("Thank you! Your feedback has been submitted.")
        return redirect(url_for("feedback"))

    return render_template("feedback.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "College123"

@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        return "Invalid Admin Username or Password"

    return render_template("admin_login.html")


@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    conn = get_db_connection()
    complaints = conn.execute("""
        SELECT complaints.id, complaints.subject, complaints.description,
               complaints.category, complaints.status, complaints.created_at,
               complaints.photo, students.name, students.email,
               students.department, students.phone
        FROM complaints
        JOIN students ON complaints.student_id = students.id
        ORDER BY complaints.id DESC
    """).fetchall()

    feedback_list = conn.execute("""
        SELECT feedback.id, feedback.rating, feedback.comment,
               feedback.created_at, students.name, students.email
        FROM feedback
        JOIN students ON feedback.student_id = students.id
        ORDER BY feedback.id DESC
    """).fetchall()
    conn.close()

    return render_template(
        "admin.html",
        complaints=complaints,
        feedback_list=feedback_list
    )


@app.route("/update_status/<int:complaint_id>", methods=["POST"])
def update_status(complaint_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    status = request.form["status"]
    allowed_status = ["Pending", "In Progress", "Resolved", "Rejected"]
    if status not in allowed_status:
        return "Invalid Status", 400

    conn = get_db_connection()
    conn.execute(
        "UPDATE complaints SET status = ? WHERE id = ?",
        (status, complaint_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin_logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


STAFF_USERNAME = "staff"
STAFF_PASSWORD = "Staff123"

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        if username == STAFF_USERNAME and password == STAFF_PASSWORD:
            session["staff_logged_in"] = True
            return redirect(url_for("staff_dashboard"))

        return "Invalid Staff Username or Password"

    return render_template("staff_login.html")


@app.route("/staff")
def staff_dashboard():
    if not session.get("staff_logged_in"):
        return redirect(url_for("staff_login"))

    conn = get_db_connection()
    complaints = conn.execute("""
        SELECT complaints.id, complaints.subject, complaints.description,
               complaints.category, complaints.status, complaints.created_at,
               complaints.photo, students.name, students.email,
               students.department, students.phone
        FROM complaints
        JOIN students ON complaints.student_id = students.id
        ORDER BY complaints.id DESC
    """).fetchall()
    conn.close()

    return render_template("staff.html", complaints=complaints)


@app.route("/staff_update_status/<int:complaint_id>", methods=["POST"])
def staff_update_status(complaint_id):
    if not session.get("staff_logged_in"):
        return redirect(url_for("staff_login"))

    status = request.form["status"]
    allowed_status = ["Pending", "In Progress", "Resolved", "Rejected"]
    if status not in allowed_status:
        return "Invalid Status", 400

    conn = get_db_connection()
    conn.execute(
        "UPDATE complaints SET status = ? WHERE id = ?",
        (status, complaint_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("staff_dashboard"))


@app.route("/staff_logout")
def staff_logout():
    session.pop("staff_logged_in", None)
    return redirect(url_for("staff_login"))


# Initialize the database when the app starts (including under Gunicorn).
init_db()

if __name__ == "__main__":
    app.run(debug=True)
