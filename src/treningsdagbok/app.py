import calendar
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from importlib import resources

import click
from flask import Flask, Response, abort, g, redirect, render_template, request, url_for

from . import charts

FIELDS = ("high", "moderate", "low", "strength", "stretch")
LABELS = {
    "high": "Høy",
    "moderate": "Mod",
    "low": "Lav",
    "strength": "Styrke",
    "stretch": "Tøy",
}
DAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]
MONTHS = [
    "jan",
    "feb",
    "mars",
    "april",
    "mai",
    "juni",
    "juli",
    "aug",
    "sept",
    "okt",
    "nov",
    "des",
]
USERNAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

# schema.sql is the baseline (user_version 0). Each entry here is applied once,
# in order, and the position (1-based) is stored in PRAGMA user_version.
MIGRATIONS = [
    """
    ALTER TABLE sessions ADD COLUMN strava_id INTEGER;
    CREATE UNIQUE INDEX sessions_strava_id ON sessions(strava_id)
      WHERE strava_id IS NOT NULL;
    """,
]


def parse_duration(text):
    """'1:30' -> 90, '1:30:00' -> 90, '45' -> 45 (minutes), '' -> 0."""
    text = (text or "").strip()
    if not text:
        return 0
    m = re.fullmatch(r"(\d{1,3}):(\d{1,2})(?::\d{1,2})?", text)
    if m:
        return int(m[1]) * 60 + int(m[2])
    if re.fullmatch(r"\d{1,4}", text):
        return int(text)
    msg = f"Ugyldig tid: {text!r} (bruk t:mm eller minutter)"
    raise ValueError(msg)


def parse_strava_id(text):
    """'12345' -> (12345, None), '' -> (None, None), junk -> (None, error)."""
    text = (text or "").strip()
    if not text:
        return None, None
    if re.fullmatch(r"\d{1,18}", text) and int(text) > 0:
        return int(text), None
    return None, "Ugyldig Strava-id."


def fmt_duration(minutes) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def fmt_duration_blank(minutes):
    return fmt_duration(minutes) if minutes else ""


def short_date(d) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{DAYS[d.weekday()]}, {d.day}. {MONTHS[d.month - 1]}"


def create_app(config=None):
    app = Flask(__name__)
    app.config["DATABASE"] = os.environ.get("TRENING_DB", "trening.sqlite3")
    if config:
        app.config.update(config)

    app.jinja_env.filters["dur"] = fmt_duration
    app.jinja_env.filters["durblank"] = fmt_duration_blank
    app.jinja_env.filters["shortdate"] = short_date
    app.jinja_env.globals.update(
        shortdate=short_date, FIELDS=FIELDS, LABELS=LABELS, MONTHS=MONTHS
    )

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db() -> None:
        db = get_db()
        db.executescript(
            resources.files(__package__).joinpath("schema.sql").read_text()
        )
        version = db.execute("PRAGMA user_version").fetchone()[0]
        for number, migration in enumerate(MIGRATIONS, start=1):
            if number > version:
                db.executescript(
                    f"BEGIN; {migration} PRAGMA user_version = {number}; COMMIT;"
                )
        db.commit()

    app.init_db = init_db

    # ---- helpers -------------------------------------------------------
    def user_or_404(username):
        row = (
            get_db()
            .execute("SELECT * FROM users WHERE username = ?", (username,))
            .fetchone()
        )
        if row is None:
            abort(404)
        return row

    def sessions_between(username, start, end):
        """Sessions with start <= date < end (ISO date strings)."""
        return (
            get_db()
            .execute(
                "SELECT * FROM sessions WHERE username = ? AND date >= ? "
                "AND date < ? ORDER BY date, id",
                (username, start, end),
            )
            .fetchall()
        )

    def totals(rows):
        t = {f: sum(r[f] for r in rows) for f in FIELDS}
        t["total"] = sum(t[f] for f in FIELDS)
        t["count"] = len(rows)
        return t

    def row_total(r):
        return sum(r[f] for f in FIELDS)

    app.jinja_env.globals["row_total"] = row_total

    def week_range(year, week):
        monday = date.fromisocalendar(year, week, 1)
        return monday, monday + timedelta(days=7)

    def weeks_in_year(year):
        return date(year, 12, 28).isocalendar()[1]

    def shift_week(year, week, delta):
        monday = date.fromisocalendar(year, week, 1) + timedelta(weeks=delta)
        iso = monday.isocalendar()
        return iso[0], iso[1]

    def read_form(form):
        errors, values = [], {}
        raw = {k: form.get(k, "").strip() for k in ("date", "what", "details", *FIELDS)}
        try:
            values["date"] = date.fromisoformat(raw["date"]).isoformat()
        except ValueError:
            errors.append("Ugyldig dato (bruk ÅÅÅÅ-MM-DD).")
        for f in FIELDS:
            try:
                values[f] = parse_duration(raw[f])
            except ValueError as e:
                errors.append(f"{LABELS[f]}: {e}")
        values["what"] = raw["what"]
        values["details"] = form.get("details", "").strip()
        values["important"] = 1 if form.get("important") else 0
        values["strava_id"], strava_error = parse_strava_id(form.get("strava_id"))
        if strava_error:
            errors.append(strava_error)
        return values, raw, errors

    # ---- routes --------------------------------------------------------
    @app.route("/")
    def index():
        users = get_db().execute("SELECT * FROM users ORDER BY full_name").fetchall()
        return render_template("index.html", users=users)

    @app.route("/<username>/")
    def user_home(username):
        user_or_404(username)
        view = request.args.get("view", "uke")
        last = (
            get_db()
            .execute("SELECT MAX(date) FROM sessions WHERE username = ?", (username,))
            .fetchone()[0]
        )
        d = date.fromisoformat(last) if last else date.today()
        if view == "maaned":
            return redirect(
                url_for("month_view", username=username, year=d.year, month=d.month)
            )
        iso = d.isocalendar()
        return redirect(
            url_for("week_view", username=username, year=iso[0], week=iso[1])
        )

    @app.route("/<username>/uke/<int:year>/<int:week>")
    def week_view(username, year, week):
        user = user_or_404(username)
        if not (1900 <= year <= 2200 and 1 <= week <= weeks_in_year(year)):
            abort(404)
        start, end = week_range(year, week)
        rows = sessions_between(username, start.isoformat(), end.isoformat())
        py, pw = shift_week(year, week, -1)
        ny, nw = shift_week(year, week, 1)
        return render_template(
            "period.html",
            user=user,
            view="uke",
            rows=rows,
            totals=totals(rows),
            title=f"{year}, uke {week}",
            prev=url_for("week_view", username=username, year=py, week=pw),
            next=url_for("week_view", username=username, year=ny, week=nw),
            date_fmt=short_date,
        )

    @app.route("/<username>/maaned/<int:year>/<int:month>")
    def month_view(username, year, month):
        user = user_or_404(username)
        if not (1900 <= year <= 2200 and 1 <= month <= 12):
            abort(404)
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        rows = sessions_between(username, start.isoformat(), end.isoformat())
        py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
        ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
        return render_template(
            "period.html",
            user=user,
            view="maaned",
            rows=rows,
            totals=totals(rows),
            title=f"{year}-{month:02d}",
            prev=url_for("month_view", username=username, year=py, month=pm),
            next=url_for("month_view", username=username, year=ny, month=nm),
            date_fmt=lambda d: d,
        )

    @app.route("/<username>/ny", methods=["GET", "POST"])
    def new_session(username):
        user = user_or_404(username)
        if request.method == "POST":
            values, raw, errors = read_form(request.form)
            if not errors:
                db = get_db()
                try:
                    cur = db.execute(
                        "INSERT INTO sessions (username, date, what, high, "
                        "moderate, low, strength, stretch, details, important, "
                        "strava_id) VALUES (:username, :date, :what, :high, "
                        ":moderate, :low, :strength, :stretch, :details, "
                        ":important, :strava_id)",
                        {**values, "username": username},
                    )
                except sqlite3.IntegrityError:
                    errors.append("Strava-økta er allerede registrert.")
                else:
                    db.commit()
                    response = redirect(url_for("user_home", username=username))
                    response.headers["X-Session-Id"] = str(cur.lastrowid)
                    return response
            return render_template(
                "form.html",
                user=user,
                s=raw,
                important=values["important"],
                errors=errors,
                mode="new",
            ), 400
        blank = {
            "date": date.today().isoformat(),
            "what": "",
            "details": "",
            **dict.fromkeys(FIELDS, ""),
        }
        return render_template(
            "form.html", user=user, s=blank, important=0, errors=[], mode="new"
        )

    def get_session_or_404(username, sid):
        row = (
            get_db()
            .execute(
                "SELECT * FROM sessions WHERE id = ? AND username = ?", (sid, username)
            )
            .fetchone()
        )
        if row is None:
            abort(404)
        return row

    @app.route("/<username>/<int:sid>/endre", methods=["GET", "POST"])
    def edit_session(username, sid):
        user = user_or_404(username)
        row = get_session_or_404(username, sid)
        if request.method == "POST":
            values, raw, errors = read_form(request.form)
            if not errors:
                db = get_db()
                db.execute(
                    "UPDATE sessions SET date=:date, what=:what, high=:high, "
                    "moderate=:moderate, low=:low, strength=:strength, "
                    "stretch=:stretch, details=:details, "
                    "important=:important WHERE id=:id",
                    {**values, "id": sid},
                )
                db.commit()
                iso = date.fromisoformat(values["date"]).isocalendar()
                return redirect(
                    url_for("week_view", username=username, year=iso[0], week=iso[1])
                )
            return render_template(
                "form.html",
                user=user,
                s=raw,
                important=values["important"],
                errors=errors,
                mode="edit",
                sid=sid,
            ), 400
        s = {
            "date": row["date"],
            "what": row["what"],
            "details": row["details"],
            **{f: fmt_duration_blank(row[f]) for f in FIELDS},
        }
        return render_template(
            "form.html",
            user=user,
            s=s,
            important=row["important"],
            errors=[],
            mode="edit",
            sid=sid,
        )

    @app.post("/<username>/<int:sid>/strava")
    def set_strava_id(username, sid):
        user_or_404(username)
        get_session_or_404(username, sid)
        strava_id, error = parse_strava_id(request.form.get("strava_id"))
        if error or strava_id is None:
            abort(400)
        db = get_db()
        try:
            db.execute(
                "UPDATE sessions SET strava_id = ? WHERE id = ?", (strava_id, sid)
            )
        except sqlite3.IntegrityError:
            abort(409)
        db.commit()
        return "", 204

    @app.post("/<username>/<int:sid>/slett")
    def delete_session(username, sid):
        user_or_404(username)
        get_session_or_404(username, sid)
        db = get_db()
        db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        db.commit()
        return redirect(url_for("user_home", username=username))

    @app.route("/<username>/sok")
    def search(username):
        user = user_or_404(username)
        q = {k: request.args.get(k, "").strip() for k in ("hva", "aar", "detaljer")}
        rows, searched = [], any(q.values())
        if searched:
            where, params = ["username = ?"], [username]
            if q["aar"]:
                if not re.fullmatch(r"\d{4}", q["aar"]):
                    abort(400)
                where.append("substr(date, 1, 4) = ?")
                params.append(q["aar"])
            for col, key in (("what", "hva"), ("details", "detaljer")):
                if q[key]:
                    where.append(f"{col} LIKE ? ESCAPE '\\'")
                    esc = re.sub(r"([\\%_])", r"\\\1", q[key])
                    params.append(f"%{esc}%")
            rows = (
                get_db()
                .execute(
                    "SELECT * FROM sessions WHERE "
                    + " AND ".join(where)
                    + " ORDER BY date, id",
                    params,
                )
                .fetchall()
            )
        return render_template(
            "search.html",
            user=user,
            q=q,
            rows=rows,
            searched=searched,
            totals=totals(rows),
        )

    def all_rows(username):
        return (
            get_db()
            .execute(
                "SELECT date, high, moderate, low, strength, stretch "
                "FROM sessions WHERE username = ? ORDER BY date",
                (username,),
            )
            .fetchall()
        )

    def group(rows, keyfn):
        buckets = defaultdict(list)
        for r in rows:
            buckets[keyfn(date.fromisoformat(r["date"]))].append(r)
        return {k: totals(v) for k, v in sorted(buckets.items())}

    @app.route("/<username>/sammendrag")
    def summary(username):
        user = user_or_404(username)
        view = "uke" if request.args.get("view") == "uke" else "maaned"
        rows = all_rows(username)
        years = sorted({int(r["date"][:4]) for r in rows}, reverse=True)
        if view == "uke":
            year = request.args.get("aar", type=int) or (
                years[0] if years else date.today().year
            )
            # ISO weeks belong to the ISO year, not the calendar year
            data = group(
                [
                    r
                    for r in rows
                    if date.fromisoformat(r["date"]).isocalendar()[0] == year
                ],
                lambda d: d.isocalendar()[1],
            )
            labels = {k: f"Uke {k}" for k in data}
            overall = {
                year: totals(
                    [
                        r
                        for r in rows
                        if date.fromisoformat(r["date"]).isocalendar()[0] == year
                    ]
                )
            }
        else:
            year = None
            by_month = group(rows, lambda d: (d.year, d.month))
            data = by_month
            labels = {k: f"{k[0]}-{k[1]:02d}" for k in data}
            overall = group(rows, lambda d: d.year)
        return render_template(
            "summary.html",
            user=user,
            view=view,
            data=data,
            labels=labels,
            overall=overall,
            years=years,
            year=year,
        )

    @app.route("/<username>/graf/<kind>.svg")
    def chart(username, kind):
        user_or_404(username)
        if kind not in ("maaned", "uke"):
            abort(404)
        rows = all_rows(username)
        if kind == "maaned":
            data = group(rows, lambda d: f"{d.year}-{d.month:02d}")
        else:
            data = group(rows, lambda d: "%d-W%02d" % d.isocalendar()[:2])
        svg = charts.line_chart(
            list(data),
            {LABELS[f]: [data[k][f] / 60 for k in data] for f in FIELDS}
            | {"Totalt": [data[k]["total"] / 60 for k in data]},
        )
        return Response(svg, mimetype="image/svg+xml")

    # ---- CLI -----------------------------------------------------------
    @app.cli.command("init-db")
    def init_db_cmd() -> None:
        """Create the database tables."""
        init_db()
        click.echo("OK")

    @app.cli.command("add-user")
    @click.argument("username")
    @click.argument("full_name")
    def add_user_cmd(username, full_name) -> None:
        """Add (or rename) a user, e.g. add-user anna 'Anna Nordmann'."""
        if not USERNAME_RE.match(username):
            msg = "a-z, 0-9, _ and - only"
            raise click.BadParameter(msg)
        init_db()
        db = get_db()
        db.execute(
            "INSERT INTO users VALUES (?, ?) ON CONFLICT(username) "
            "DO UPDATE SET full_name = excluded.full_name",
            (username, full_name),
        )
        db.commit()

    return app


def wsgi():
    """Entry point for gunicorn: `gunicorn 'treningsdagbok:wsgi()'`."""
    application = create_app()
    with application.app_context():
        application.init_db()
    return application
