CREATE TABLE IF NOT EXISTS users (
  username  TEXT PRIMARY KEY,
  full_name TEXT NOT NULL
);

-- Durations are stored as whole minutes.
CREATE TABLE IF NOT EXISTS sessions (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  username  TEXT NOT NULL REFERENCES users(username),
  date      TEXT NOT NULL,            -- ISO date, YYYY-MM-DD
  what      TEXT NOT NULL DEFAULT '',
  high      INTEGER NOT NULL DEFAULT 0,
  moderate  INTEGER NOT NULL DEFAULT 0,
  low       INTEGER NOT NULL DEFAULT 0,
  strength  INTEGER NOT NULL DEFAULT 0,
  stretch   INTEGER NOT NULL DEFAULT 0,
  details   TEXT NOT NULL DEFAULT '',
  important INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS sessions_user_date ON sessions(username, date);
