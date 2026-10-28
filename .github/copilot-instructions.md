# Copilot instructions

Flask + SQLite rewrite of a 2002 PHP/MySQL training diary. UI text, URLs and variable names are partly Norwegian (`uke`=week, `maaned`=month, `ny`=new, `endre`=edit, `sok`=search, `sammendrag`=summary, `graf`=chart).

## Commands

    pip install -e '.[test]'                 # or use uv (uv.lock is checked in)
    pytest                                   # full suite
    pytest tests/test_app.py::test_parse_duration   # single test
    ruff check --fix . && ruff format .      # lint/format (also run by pre-commit)

Run locally:

    export TRENING_DB=$PWD/trening.sqlite3 FLASK_APP=treningsdagbok
    flask run

Production: `gunicorn 'treningsdagbok:wsgi()'` (see `nixos/treningsdagbok.nix`); `wsgi()` calls `init_db()` on start.

## Architecture

- `src/treningsdagbok/app.py` holds nearly everything (`__init__.py` only re-exports `create_app`, `wsgi`, `parse_duration`, `fmt_duration`; keep code out of `__init__.py`): `create_app()` is an app factory, and all routes, DB helpers, Jinja filters/globals and CLI commands (`init-db`, `add-user`) are closures defined inside it. `app.init_db` is attached to the app object.
- DB path comes from `TRENING_DB` env or the `DATABASE` config key (tests pass `DATABASE` to `create_app`). SQLite connection is per-request via `g`, with `row_factory = sqlite3.Row` and foreign keys on.
- Schema is `src/treningsdagbok/schema.sql` (idempotent `CREATE ... IF NOT EXISTS`, no migrations). Dates are ISO `YYYY-MM-DD` text; **durations are stored as whole minutes** in the intensity columns listed in `FIELDS` (`high, moderate, low, strength, stretch`). Adding a field means updating `FIELDS`/`LABELS`, the schema, `read_form` and templates.
- All routes are scoped per user: `/<username>/...`, guarded by `user_or_404`. There is intentionally **no authentication**.
- Week views use proper ISO weeks (`date.fromisocalendar`); date-range queries use half-open `[start, end)`.
- `charts.py` renders SVG charts server-side (no JS/gnuplot), served from `/<username>/graf/<kind>.svg`.
- Templates/static/schema are shipped via `[tool.setuptools.package-data]`; add new asset types there.

## Conventions

- Durations are parsed with `parse_duration` (`h:mm`, `h:mm:ss`, or plain minutes) and displayed with the `dur`/`durblank` filters; it raises `ValueError` with a Norwegian message, which `read_form` collects into user-facing errors.
- Always use parameterized SQL; user content is rendered through Jinja autoescaping (tests check `<b>` is escaped).
- Tests use a `client` fixture with a temp DB and call `add-user` via `test_cli_runner`; new route tests follow `tests/test_app.py`.
- Ruff uses a broad rule set (line length 88; includes `EM`, `TRY`, `FBT`, `T`, `ERA`, `RET`): assign exception messages to `msg` before raising, no print, no commented-out code.
