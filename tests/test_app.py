import sqlite3
from importlib.resources import files

import pytest

from treningsdagbok import create_app, fmt_duration, parse_duration


@pytest.fixture
def client(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "t.sqlite3"), "TESTING": True})
    with app.app_context():
        app.init_db()
    runner = app.test_cli_runner()
    assert runner.invoke(args=["add-user", "anna", "Anna Nordmann"]).exit_code == 0
    return app.test_client()


def add(client, **kw):
    data = {
        "date": "2024-01-03",
        "what": "Løping",
        "high": "0:20",
        "moderate": "1:00",
        "details": "<b>x</b>",
        **kw,
    }
    return client.post("/anna/ny", data=data)


def test_parse_duration() -> None:
    assert parse_duration("1:30") == 90
    assert parse_duration("1:30:00") == 90
    assert parse_duration("45") == 45
    assert parse_duration("") == 0
    with pytest.raises(ValueError):
        parse_duration("abc")
    assert fmt_duration(65) == "1:05"


def test_add_view_sums_and_escaping(client) -> None:
    assert add(client).status_code == 302
    add(client, date="2024-01-04", high="0:10", moderate="")
    html = client.get("/anna/uke/2024/1").get_data(as_text=True)
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html
    assert "1:20" in html  # first session total
    assert "1:30" in html  # week total
    assert "2024-01-03" not in client.get("/anna/uke/2024/2").get_data(as_text=True)


def test_iso_week_across_year_boundary(client) -> None:
    add(client, date="2024-12-30")  # ISO week 1 of 2025
    assert "Løping" in client.get("/anna/uke/2025/1").get_data(as_text=True)
    assert "Løping" not in client.get("/anna/uke/2024/52").get_data(as_text=True)
    assert "Løping" in client.get("/anna/maaned/2024/12").get_data(as_text=True)


def test_invalid_input_rejected(client) -> None:
    r = add(client, date="nope", high="x")
    assert r.status_code == 400
    assert "Ugyldig dato" in r.get_data(as_text=True)


def test_edit_and_delete(client) -> None:
    add(client)
    assert (
        client.post(
            "/anna/1/endre",
            data={"date": "2024-01-03", "what": "Sykling", "important": "1"},
        ).status_code
        == 302
    )
    html = client.get("/anna/uke/2024/1").get_data(as_text=True)
    assert "Sykling" in html
    assert 'class="viktig"' in html
    assert client.post("/anna/1/slett").status_code == 302
    assert client.get("/anna/1/endre").status_code == 404


def test_search_is_literal_and_injection_safe(client) -> None:
    add(client, what="100% hard")
    add(client, what="easy")
    html = client.get("/anna/sok?hva=100%25").get_data(as_text=True)
    assert "1 treff" in html
    assert "0 treff" in client.get("/anna/sok?hva=' OR 1=1 --").get_data(as_text=True)


def test_unknown_user_and_pages(client) -> None:
    assert client.get("/nobody/").status_code == 404
    add(client)
    for url in (
        "/",
        "/anna/",
        "/anna/sammendrag",
        "/anna/sammendrag?view=uke",
        "/anna/sok",
        "/anna/graf/maaned.svg",
        "/anna/graf/uke.svg",
    ):
        assert client.get(url, follow_redirects=True).status_code == 200, url


def test_empty_chart(client) -> None:
    assert client.get("/anna/graf/uke.svg").status_code == 200


def test_strava_link_and_icon(client) -> None:
    resp = add(client, strava_id="123456")
    assert resp.status_code == 302
    sid = resp.headers["X-Session-Id"]
    html = client.get("/anna/uke/2024/1").get_data(as_text=True)
    assert "https://www.strava.com/activities/123456" in html

    assert add(client, date="2024-01-05", strava_id="123456").status_code == 400
    assert add(client, date="2024-01-05", strava_id="abc").status_code == 400

    other = add(client, date="2024-01-05")
    other_sid = other.headers["X-Session-Id"]
    assert (
        client.post(f"/anna/{other_sid}/strava", data={"strava_id": "9"}).status_code
        == 204
    )
    assert (
        client.post(
            f"/anna/{other_sid}/strava", data={"strava_id": "123456"}
        ).status_code
        == 409
    )
    assert (
        client.post(f"/anna/{sid}/strava", data={"strava_id": "x"}).status_code == 400
    )

    client.post(f"/anna/{sid}/endre", data={"date": "2024-01-03", "what": "Ny"})
    html = client.get("/anna/uke/2024/1").get_data(as_text=True)
    assert "activities/123456" in html

    assert 'value="123456"' in client.get(f"/anna/{sid}/endre").get_data(as_text=True)
    edit = {"date": "2024-01-03", "what": "Ny"}
    assert (
        client.post(f"/anna/{sid}/endre", data={**edit, "strava_id": "9"}).status_code
        == 400
    )
    assert (
        client.post(f"/anna/{sid}/endre", data={**edit, "strava_id": "77"}).status_code
        == 302
    )
    assert "activities/77" in client.get("/anna/uke/2024/1").get_data(as_text=True)
    client.post(f"/anna/{sid}/endre", data={**edit, "strava_id": ""})
    assert "activities/77" not in client.get("/anna/uke/2024/1").get_data(as_text=True)


def test_migrates_old_database(tmp_path) -> None:
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(
        files("treningsdagbok").joinpath("schema.sql").read_text()
        + "INSERT INTO users VALUES ('anna', 'Anna');"
        "INSERT INTO sessions (username, date) VALUES ('anna', '2024-01-03');"
    )
    db.close()
    app = create_app({"DATABASE": str(path), "TESTING": True})
    with app.app_context():
        app.init_db()
        app.init_db()
        db = sqlite3.connect(path)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT strava_id FROM sessions").fetchone() == (None,)


def test_only_owner_can_write(tmp_path) -> None:
    app = create_app(
        {
            "DATABASE": str(tmp_path / "t.sqlite3"),
            "TESTING": True,
            "AUTH_HEADER": "X-Remote-User",
        }
    )
    with app.app_context():
        app.init_db()
    runner = app.test_cli_runner()
    runner.invoke(args=["add-user", "anna", "Anna"])
    runner.invoke(args=["add-user", "bob", "Bob"])
    client = app.test_client()
    as_anna = {"X-Remote-User": "anna"}
    form = {"date": "2024-01-03", "what": "Løping", "low": "1:00"}

    sid = client.post("/anna/ny", data=form, headers=as_anna).headers["X-Session-Id"]
    assert (
        client.post("/anna/ny", data=form, headers={"X-Remote-User": "bob"}).status_code
        == 403
    )
    assert client.post("/anna/ny", data=form).status_code == 403
    for method, url in (
        ("get", "/anna/ny"),
        ("get", f"/anna/{sid}/endre"),
        ("post", f"/anna/{sid}/endre"),
        ("post", f"/anna/{sid}/slett"),
        ("post", f"/anna/{sid}/strava"),
    ):
        resp = getattr(client, method)(url, headers={"X-Remote-User": "bob"})
        assert resp.status_code == 403, url

    page = "/anna/uke/2024/1"
    assert "Legg inn" in client.get(page, headers=as_anna).get_data(as_text=True)
    other = client.get(page, headers={"X-Remote-User": "bob"}).get_data(as_text=True)
    assert "Løping" in other
    assert "Legg inn" not in other
    assert "/endre" not in other

    resp = client.get("/", headers=as_anna)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/anna/")
    assert client.get("/?alle=1", headers=as_anna).status_code == 200
    assert client.get("/").status_code == 200
