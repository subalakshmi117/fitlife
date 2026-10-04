from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DEFAULT_DB = ROOT / "data" / "fitlife.sqlite3"
SESSION_TTL = 60 * 60 * 24 * 7
PASSWORD_ITERATIONS = 310_000
MAX_BODY_BYTES = 32_768
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOG = logging.getLogger("fitlife")


def load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()
HOST = os.environ.get("FITLIFE_HOST", "127.0.0.1")
PORT = int(os.environ.get("FITLIFE_PORT", "8000"))
DB_PATH = Path(os.environ.get("FITLIFE_DATABASE", str(DEFAULT_DB))).expanduser()
COOKIE_SECURE = os.environ.get("FITLIFE_COOKIE_SECURE", "false").lower() == "true"
COOKIE_NAME = "fitlife_session"


WORKOUTS = [
    {
        "id": "full-body",
        "name": "Full-body foundations",
        "category": "Strength",
        "level": "Beginner",
        "duration": 30,
        "days": "3 days / week",
        "icon": "◉",
        "description": "Build confidence with approachable, full-body strength sessions.",
        "exercises": ["Bodyweight squats · 3 × 10", "Incline push-ups · 3 × 8", "Glute bridges · 3 × 12", "Dead bugs · 3 × 8 / side"],
    },
    {
        "id": "gentle-cardio",
        "name": "Feel-good cardio",
        "category": "Cardio",
        "level": "All levels",
        "duration": 25,
        "days": "2–3 days / week",
        "icon": "↗",
        "description": "A low-pressure walk-and-move routine to lift your energy.",
        "exercises": ["Easy walk · 5 min", "Brisk walk · 15 min", "Cool-down stroll · 5 min"],
    },
    {
        "id": "mobility-reset",
        "name": "Daily mobility reset",
        "category": "Mobility",
        "level": "Beginner",
        "duration": 15,
        "days": "Most days",
        "icon": "✳",
        "description": "Gentle stretches to make more room for movement in your day.",
        "exercises": ["Cat-cow · 8 reps", "World's greatest stretch · 5 / side", "Seated twist · 30 sec / side", "Child's pose · 60 sec"],
    },
]

MEALS = [
    {"name": "A brighter breakfast", "time": "BREAKFAST", "calories": 390, "icon": "◒", "items": "Greek yogurt, berries, oats & a spoon of honey"},
    {"name": "The feel-good bowl", "time": "LUNCH", "calories": 520, "icon": "◉", "items": "Quinoa, roasted chickpeas, greens & lemon tahini"},
    {"name": "A little afternoon energy", "time": "SNACK", "calories": 190, "icon": "✳", "items": "Apple slices with almond butter"},
    {"name": "Easy evening plate", "time": "DINNER", "calories": 560, "icon": "◒", "items": "Salmon or tofu, brown rice & colorful vegetables"},
]


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                age INTEGER,
                gender TEXT NOT NULL DEFAULT '',
                height_cm REAL,
                weight_kg REAL,
                goal TEXT NOT NULL DEFAULT 'Build a healthy routine',
                level TEXT NOT NULL DEFAULT 'Beginner',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                entry_date TEXT NOT NULL,
                workout TEXT NOT NULL,
                minutes INTEGER NOT NULL CHECK (minutes BETWEEN 1 AND 600),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS progress_user_date ON progress(user_id, entry_date DESC);
            CREATE TABLE IF NOT EXISTS workout_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                level TEXT NOT NULL,
                duration INTEGER NOT NULL CHECK (duration BETWEEN 1 AND 600),
                days TEXT NOT NULL,
                icon TEXT NOT NULL,
                description TEXT NOT NULL,
                exercises TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meal_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                time TEXT NOT NULL,
                calories INTEGER NOT NULL CHECK (calories >= 0),
                icon TEXT NOT NULL,
                items TEXT NOT NULL
            );
            """
        )
        db.executemany(
            """
            INSERT OR IGNORE INTO workout_plans
                (id, name, category, level, duration, days, icon, description, exercises)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    workout["id"],
                    workout["name"],
                    workout["category"],
                    workout["level"],
                    workout["duration"],
                    workout["days"],
                    workout["icon"],
                    workout["description"],
                    json.dumps(workout["exercises"]),
                )
                for workout in WORKOUTS
            ],
        )
        db.executemany(
            "INSERT OR IGNORE INTO meal_plans (name, time, calories, icon, items) VALUES (?, ?, ?, ?, ?)",
            [
                (meal["name"], meal["time"], meal["calories"], meal["icon"], meal["items"])
                for meal in MEALS
            ],
        )
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))


def password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "age": row["age"],
        "gender": row["gender"],
        "height_cm": row["height_cm"],
        "weight_kg": row["weight_kg"],
        "goal": row["goal"],
        "level": row["level"],
    }


def validate_profile(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not 1 <= len(name) <= 70:
        raise ValueError("Name must be between 1 and 70 characters.")
    age = payload.get("age")
    if age in ("", None):
        age = None
    else:
        try:
            age = int(age)
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a valid age.") from exc
        if not 13 <= age <= 120:
            raise ValueError("Age must be between 13 and 120.")
    height = payload.get("height_cm")
    weight = payload.get("weight_kg")
    try:
        height = float(height) if height not in ("", None) else None
        weight = float(weight) if weight not in ("", None) else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Height and weight must be valid numbers.") from exc
    if height is not None and not 80 <= height <= 250:
        raise ValueError("Height must be between 80 and 250 cm.")
    if weight is not None and not 25 <= weight <= 350:
        raise ValueError("Weight must be between 25 and 350 kg.")
    gender = str(payload.get("gender", "")).strip()
    if gender not in ("", "Woman", "Man", "Non-binary", "Prefer not to say"):
        raise ValueError("Choose a valid gender option.")
    goal = str(payload.get("goal", "Build a healthy routine")).strip()
    if not 1 <= len(goal) <= 100:
        raise ValueError("Your goal must be between 1 and 100 characters.")
    level = str(payload.get("level", "Beginner")).strip()
    if level not in ("Beginner", "Intermediate", "Advanced"):
        raise ValueError("Choose a valid experience level.")
    return {
        "name": name,
        "age": age,
        "gender": gender,
        "height_cm": height,
        "weight_kg": weight,
        "goal": goal,
        "level": level,
    }


def validate_email(value: object) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Enter a valid email address.")
    return email


class FitLifeHandler(BaseHTTPRequestHandler):
    server_version = "FitLife/1.0"

    def log_message(self, format_string: str, *args: object) -> None:
        LOG.info("%s - %s", self.address_string(), format_string % args)

    def send_json(self, status: HTTPStatus, payload: dict, headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request size.") from exc
        if length < 1 or length > MAX_BODY_BYTES:
            raise ValueError("Request must include a JSON body under 32 KB.")
        if "application/json" not in self.headers.get("Content-Type", "").lower():
            raise ValueError("Send data using JSON.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("The request body is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("The request body must be a JSON object.")
        return payload

    def get_session(self) -> tuple[sqlite3.Row | None, str | None]:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else None
        except (KeyError, CookieError):
            token = None
        if not token or len(token) > 128:
            return None, None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with connect_db() as db:
            row = db.execute(
                "SELECT users.*, sessions.token_hash FROM sessions "
                "JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                (token_hash, int(time.time())),
            ).fetchone()
        return row, token_hash

    def set_session_cookie(self, token: str, max_age: int = SESSION_TTL) -> str:
        cookie = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        if COOKIE_SECURE:
            cookie += "; Secure"
        return cookie

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with connect_db() as db:
            db.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), user_id, int(time.time()) + SESSION_TTL),
            )
        return token

    def require_user(self) -> tuple[sqlite3.Row, str]:
        row, token_hash = self.get_session()
        if row is None or token_hash is None:
            raise PermissionError("Please sign in to continue.")
        return row, token_hash

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            try:
                if path == "/api/me":
                    user, _ = self.require_user()
                    self.send_json(HTTPStatus.OK, {"user": public_user(user)})
                elif path == "/api/plans":
                    with connect_db() as db:
                        workouts = db.execute(
                            "SELECT id, name, category, level, duration, days, icon, description, exercises "
                            "FROM workout_plans ORDER BY name"
                        ).fetchall()
                        meals = db.execute(
                            "SELECT name, time, calories, icon, items FROM meal_plans ORDER BY id"
                        ).fetchall()
                    self.send_json(
                        HTTPStatus.OK,
                        {
                            "workouts": [
                                {**dict(workout), "exercises": json.loads(workout["exercises"])}
                                for workout in workouts
                            ],
                            "meals": [dict(meal) for meal in meals],
                        },
                    )
                elif path == "/api/dashboard":
                    user, _ = self.require_user()
                    with connect_db() as db:
                        entries = db.execute(
                            "SELECT id, entry_date, workout, minutes, note FROM progress "
                            "WHERE user_id = ? ORDER BY entry_date DESC, id DESC LIMIT 30",
                            (user["id"],),
                        ).fetchall()
                    today = date.today().isoformat()
                    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
                    records = [dict(entry) for entry in entries]
                    self.send_json(HTTPStatus.OK, {
                        "user": public_user(user),
                        "progress": records,
                        "stats": {
                            "workouts_this_week": sum(item["entry_date"] >= week_start for item in records),
                            "minutes_this_week": sum(item["minutes"] for item in records if item["entry_date"] >= week_start),
                            "workouts_today": sum(item["entry_date"] == today for item in records),
                        },
                    })
                else:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "That API endpoint was not found."})
            except PermissionError as exc:
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
            except Exception:
                LOG.exception("API request failed: %s %s", self.command, path)
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Something went wrong. Please try again."})
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/signup":
                profile = validate_profile({
                    "name": payload.get("name"),
                    "age": payload.get("age"),
                    "gender": payload.get("gender", ""),
                    "height_cm": payload.get("height_cm"),
                    "weight_kg": payload.get("weight_kg"),
                    "goal": payload.get("goal", "Build a healthy routine"),
                    "level": payload.get("level", "Beginner"),
                })
                email = validate_email(payload.get("email"))
                password = str(payload.get("password", ""))
                if len(password) < 8 or len(password) > 128:
                    raise ValueError("Password must be between 8 and 128 characters.")
                salt = secrets.token_bytes(16)
                with connect_db() as db:
                    cursor = db.execute(
                        "INSERT INTO users (name, email, password_hash, password_salt, age, gender, height_cm, weight_kg, goal, level, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            profile["name"], email, password_digest(password, salt).hex(), salt.hex(),
                            profile["age"], profile["gender"], profile["height_cm"], profile["weight_kg"],
                            profile["goal"], profile["level"], datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    user_id = cursor.lastrowid
                token = self.create_session(user_id)
                with connect_db() as db:
                    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                self.send_json(HTTPStatus.CREATED, {"user": public_user(user)}, {"Set-Cookie": self.set_session_cookie(token)})
            elif path == "/api/login":
                email = validate_email(payload.get("email"))
                password = str(payload.get("password", ""))
                with connect_db() as db:
                    user = db.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
                valid = False
                if user and len(password) <= 128:
                    try:
                        salt = bytes.fromhex(user["password_salt"])
                        expected = bytes.fromhex(user["password_hash"])
                        valid = hmac.compare_digest(password_digest(password, salt), expected)
                    except ValueError:
                        LOG.error("Stored password hash is invalid for user id %s", user["id"])
                if not valid:
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Email or password is incorrect."})
                    return
                token = self.create_session(user["id"])
                self.send_json(HTTPStatus.OK, {"user": public_user(user)}, {"Set-Cookie": self.set_session_cookie(token)})
            elif path == "/api/logout":
                _, token_hash = self.require_user()
                with connect_db() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                self.send_json(
                    HTTPStatus.OK,
                    {"message": "You have been signed out."},
                    {"Set-Cookie": self.set_session_cookie("", max_age=0)},
                )
            elif path == "/api/progress":
                user, _ = self.require_user()
                workout = str(payload.get("workout", "")).strip()
                if not workout or len(workout) > 100:
                    raise ValueError("Choose a workout name (up to 100 characters).")
                try:
                    minutes = int(payload.get("minutes"))
                except (TypeError, ValueError) as exc:
                    raise ValueError("Enter workout minutes as a whole number.") from exc
                if not 1 <= minutes <= 600:
                    raise ValueError("Workout duration must be between 1 and 600 minutes.")
                entry_date = str(payload.get("entry_date", date.today().isoformat()))
                try:
                    parsed_date = date.fromisoformat(entry_date)
                except ValueError as exc:
                    raise ValueError("Choose a valid workout date.") from exc
                if parsed_date > date.today() or parsed_date < date.today() - timedelta(days=3650):
                    raise ValueError("Workout date must be within the past 10 years.")
                note = str(payload.get("note", "")).strip()
                if len(note) > 300:
                    raise ValueError("Notes must be 300 characters or fewer.")
                with connect_db() as db:
                    cursor = db.execute(
                        "INSERT INTO progress (user_id, entry_date, workout, minutes, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (user["id"], entry_date, workout, minutes, note, datetime.now(timezone.utc).isoformat()),
                    )
                    entry = db.execute(
                        "SELECT id, entry_date, workout, minutes, note FROM progress WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()
                self.send_json(HTTPStatus.CREATED, {"entry": dict(entry)})
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "That API endpoint was not found."})
        except ValueError as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        except sqlite3.IntegrityError as exc:
            if path == "/api/signup" and "users.email" in str(exc):
                self.send_json(HTTPStatus.CONFLICT, {"error": "An account with this email already exists."})
            else:
                LOG.exception("Database constraint error: %s", path)
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "That change could not be saved."})
        except Exception:
            LOG.exception("API request failed: %s %s", self.command, path)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Something went wrong. Please try again."})

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        try:
            if path != "/api/profile":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "That API endpoint was not found."})
                return
            payload = self.read_json()
            user, _ = self.require_user()
            profile = validate_profile(payload)
            with connect_db() as db:
                db.execute(
                    "UPDATE users SET name = ?, age = ?, gender = ?, height_cm = ?, weight_kg = ?, goal = ?, level = ? WHERE id = ?",
                    (
                        profile["name"], profile["age"], profile["gender"], profile["height_cm"],
                        profile["weight_kg"], profile["goal"], profile["level"], user["id"],
                    ),
                )
                updated = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
            self.send_json(HTTPStatus.OK, {"user": public_user(updated)})
        except ValueError as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        except Exception:
            LOG.exception("API request failed: %s %s", self.command, path)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Something went wrong. Please try again."})

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        allowed = {"/index.html": ("index.html", "text/html; charset=utf-8"), "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8")}
        file_info = allowed.get(path)
        if not file_info:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Page not found."})
            return
        file_path = STATIC_DIR / file_info[0]
        try:
            content = file_path.read_bytes()
        except OSError:
            LOG.exception("Unable to read frontend file: %s", file_path)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "The FitLife frontend could not be loaded."})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", file_info[1])
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not 1 <= PORT <= 65535:
        raise ValueError("FITLIFE_PORT must be between 1 and 65535.")
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), FitLifeHandler)
    LOG.info("FitLife is ready at http://%s:%d", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Shutting down FitLife.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
