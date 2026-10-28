# Treningsdagbok

Rewrite of the 2002 PHP/MySQL training diary as Flask + SQLite.

- Week and month views with sums, add/edit/delete, search
- Month/week summaries with SVG charts (no gnuplot needed)
- Per-user pages at `/<user>/`. **There is no authentication**, same as the
  old `?navn=` scheme, so anyone who can reach the site can edit any diary.
  Restrict access in nginx (e.g. `auth_basic`, IP allow-list) if needed.
- Dropped: the rowing calculator and cycling entry page (not in scope).
- Week numbers are now proper ISO weeks (the old week 53 hack is gone).

## Develop

    python -m venv .venv && . .venv/bin/activate
    pip install -e '.[test]'
    export TRENING_DB=$PWD/trening.sqlite3 FLASK_APP=treningsdagbok
    flask run
    pytest

## Deploy on NixOS

Import `nixos/treningsdagbok.nix`, set `services.treningsdagbok.enable`,
`domain` and `src`. It runs gunicorn on a unix socket as a hardened systemd
service behind nginx, with data in `/var/lib/treningsdagbok/trening.sqlite3`.
Copy your database there (owner `treningsdagbok`) and restart the service.
