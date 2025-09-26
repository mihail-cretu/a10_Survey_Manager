-- surveys_schema.sql — initialize a fresh SQLite DB for the CNC A‑10 app
-- Creates all tables, constraints, indexes, and housekeeping triggers.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

BEGIN TRANSACTION;

-- Optional: clean slate (drop in FK-safe order)
DROP TABLE IF EXISTS measurement_graphs;
DROP TABLE IF EXISTS site_files;
DROP TABLE IF EXISTS measurement_images;
DROP TABLE IF EXISTS measurement_set;
DROP TABLE IF EXISTS measurement_project;
DROP TABLE IF EXISTS measurements;
DROP TABLE IF EXISTS site_images;
DROP TABLE IF EXISTS preflight_answers;
DROP TABLE IF EXISTS site_surveys;

----------------------------------------------------------------------
-- Core: Site Surveys
----------------------------------------------------------------------
CREATE TABLE site_surveys (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  code        TEXT,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'new',  -- new | preflight | measurements | completed
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (status IN ('new','preflight','measurements','completed'))
);

-- Keep updated_at fresh on any update (one extra no-op trigger fire is expected)
CREATE TRIGGER site_surveys_set_updated_at
AFTER UPDATE ON site_surveys
FOR EACH ROW
WHEN OLD.updated_at = NEW.updated_at
BEGIN
  UPDATE site_surveys
  SET updated_at = datetime('now')
  WHERE id = NEW.id;
END;

-- Helpful lookup indexes
CREATE INDEX idx_site_surveys_status ON site_surveys(status);
CREATE INDEX idx_site_surveys_code   ON site_surveys(code);

----------------------------------------------------------------------
-- Preflight checklist (answers stored per step)
----------------------------------------------------------------------
CREATE TABLE preflight_answers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  survey_id  INTEGER NOT NULL,
  step_code  TEXT NOT NULL,     -- e.g., "1.3"
  value      TEXT,               -- JSON/text for user-entered value
  checked    INTEGER,            -- 0/1
  notes      TEXT,
  UNIQUE(survey_id, step_code),
  FOREIGN KEY (survey_id) REFERENCES site_surveys(id) ON DELETE CASCADE
);

CREATE INDEX idx_preflight_answers_survey ON preflight_answers(survey_id);
CREATE INDEX idx_preflight_answers_step   ON preflight_answers(step_code);

----------------------------------------------------------------------
-- Site images (embedded BLOBs tied to the survey)
----------------------------------------------------------------------
CREATE TABLE site_images (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  survey_id    INTEGER NOT NULL,
  filename     TEXT NOT NULL,
  mime_type    TEXT,                  -- e.g., image/jpeg
  size_bytes   INTEGER,
  sha256_hex   TEXT,
  caption      TEXT,
  imported_at  TEXT NOT NULL DEFAULT (datetime('now')),
  image_blob   BLOB NOT NULL,
  FOREIGN KEY (survey_id) REFERENCES site_surveys(id) ON DELETE CASCADE
);

CREATE INDEX idx_site_images_survey ON site_images(survey_id);
CREATE INDEX idx_site_images_sha256 ON site_images(sha256_hex);

----------------------------------------------------------------------
-- Measurements container (a survey can have many measurements)
----------------------------------------------------------------------
CREATE TABLE measurements (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  survey_id   INTEGER NOT NULL,
  title       TEXT NOT NULL,
  note        TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (survey_id) REFERENCES site_surveys(id) ON DELETE CASCADE
);

CREATE INDEX idx_measurements_survey ON measurements(survey_id);
CREATE INDEX idx_measurements_created ON measurements(created_at);

----------------------------------------------------------------------
-- g9 Project import (one per measurement)
----------------------------------------------------------------------
CREATE TABLE measurement_project (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  measurement_id  INTEGER NOT NULL,
  filename        TEXT NOT NULL,   -- *.project.txt
  raw_text        TEXT NOT NULL,   -- original file content
  meta_json       TEXT NOT NULL,   -- parsed/processed fields as JSON
  imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (measurement_id),
  FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE INDEX idx_mproject_measurement ON measurement_project(measurement_id);

----------------------------------------------------------------------
-- g9 Set import (one per measurement)
----------------------------------------------------------------------
CREATE TABLE measurement_set (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  measurement_id  INTEGER NOT NULL,
  filename        TEXT NOT NULL,   -- *.set.txt
  raw_text        TEXT NOT NULL,   -- original file content
  meta_json       TEXT NOT NULL,   -- parsed/processed fields as JSON
  imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (measurement_id),
  FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE INDEX idx_mset_measurement ON measurement_set(measurement_id);

----------------------------------------------------------------------
-- Measurement images (site images attached specifically to a measurement)
----------------------------------------------------------------------
CREATE TABLE measurement_images (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  measurement_id  INTEGER NOT NULL,
  filename        TEXT NOT NULL,
  mime_type       TEXT,
  size_bytes      INTEGER,
  sha256_hex      TEXT,
  caption         TEXT,
  imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
  image_blob      BLOB NOT NULL,
  FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE INDEX idx_mimages_measurement ON measurement_images(measurement_id);
CREATE INDEX idx_mimages_sha256      ON measurement_images(sha256_hex);

----------------------------------------------------------------------
-- Measurement graphs (g9 exported graphs as BLOBs/evidence)
----------------------------------------------------------------------
CREATE TABLE measurement_graphs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  measurement_id  INTEGER NOT NULL,
  filename        TEXT NOT NULL,
  mime_type       TEXT,
  size_bytes      INTEGER,
  sha256_hex      TEXT,
  note            TEXT,
  imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
  graph_blob      BLOB NOT NULL,
  FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE INDEX idx_mgraphs_measurement ON measurement_graphs(measurement_id);
CREATE INDEX idx_mgraphs_sha256      ON measurement_graphs(sha256_hex);

----------------------------------------------------------------------
-- Site files (general supporting documents tied to a measurement)
----------------------------------------------------------------------
CREATE TABLE site_files (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  measurement_id  INTEGER NOT NULL,
  filename        TEXT NOT NULL,
  mime_type       TEXT,
  size_bytes      INTEGER,
  sha256_hex      TEXT,
  note            TEXT,
  imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
  file_blob       BLOB NOT NULL,
  FOREIGN KEY (measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
);

CREATE INDEX idx_site_files_measurement ON site_files(measurement_id);
CREATE INDEX idx_site_files_sha256      ON site_files(sha256_hex);

----------------------------------------------------------------------
-- Sanity views (optional helpers)
----------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_measurements_full AS
SELECT
  m.id                AS measurement_id,
  m.title,
  m.note,
  m.created_at,
  s.id                AS survey_id,
  s.name              AS survey_name,
  s.code              AS survey_code,
  s.status            AS survey_status,
  mp.filename         AS project_filename,
  ms.filename         AS set_filename
FROM measurements m
JOIN site_surveys s           ON s.id = m.survey_id
LEFT JOIN measurement_project mp ON mp.measurement_id = m.id
LEFT JOIN measurement_set     ms ON ms.measurement_id = m.id;

COMMIT;

-- Stamp schema version for app migrations (bump as needed)
PRAGMA user_version = 1;
