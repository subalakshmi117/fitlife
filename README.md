# FitLife

FitLife is a small, beginner-friendly fitness web app with account sign-in, a personal dashboard, workout and meal inspiration, and workout progress tracking. The backend uses Python's standard library and SQLite, so there are no third-party packages or database services to install.

## Run in VS Code

1. Open this folder in VS Code.
2. Run **Terminal → Run Task… → FitLife: Run** (or press `Ctrl+Shift+B`).
3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The task uses the system `python` command on Windows and `python3` on macOS and Linux. You can also start the app from a terminal with `python app.py` (Windows) or `python3 app.py` (macOS/Linux).

The app creates `data/fitlife.sqlite3` and its tables automatically on first launch. The database stores accounts, sessions, workout history, workout plans, and meal plans; sample plans are added automatically without overwriting existing plan records. Create an account to start a private profile and progress history.

## Configuration

Defaults work for local use without any configuration. To override them, copy `.env.example` to `.env` and set:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FITLIFE_HOST` | `127.0.0.1` | Interface to bind the local server to |
| `FITLIFE_PORT` | `8000` | Local server port |
| `FITLIFE_DATABASE` | `./data/fitlife.sqlite3` | SQLite database file |
| `FITLIFE_COOKIE_SECURE` | `false` | Set `true` when deployed over HTTPS |

Keep `.env` and the generated database private. Passwords are stored as salted PBKDF2 hashes, not as plain text. Local-only defaults are intended for development; public deployment should use HTTPS, a production-grade server, and deployment-specific security settings.

## Included features

- Create an account, sign in, and sign out
- Edit a personal profile with age, gender, height, weight, goal, and experience level
- Browse beginner-friendly workout plans by activity type
- Browse flexible meal ideas
- Record sessions, dates, durations, and personal notes
- View this week's activity and recent session history on a personal dashboard
- SQLite schema initialization, server-side validation, secure session cookies, and helpful error messages
