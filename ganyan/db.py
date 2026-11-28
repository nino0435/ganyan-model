"""SQLite database schema and upsert helpers."""
import datetime
import json
import os
import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS races (
    race_id TEXT PRIMARY KEY,
    date TEXT,
    city TEXT,
    race_no INT,
    post_time TEXT,
    yg_no INT,
    cls TEXT,
    breed TEXT,
    distance INT,
    surface TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS runners (
    race_id TEXT,
    prog_no INT,
    horse_key TEXT,
    name TEXT,
    name_raw TEXT,
    age INT,
    sex TEXT,
    sire TEXT,
    dam TEXT,
    weight REAL,
    jockey TEXT,
    owner TEXT,
    trainer TEXT,
    gate INT,
    hp REAL,
    son6 TEXT,
    kgs INT,
    s20 INT,
    best_time_s REAL,
    finish INT,
    time_s REAL,
    ganyan REAL,
    agf_close REAL,
    agf_close_rank INT,
    scratched INT,
    PRIMARY KEY(race_id, horse_key)
);

CREATE TABLE IF NOT EXISTS altili (
    date TEXT,
    city TEXT,
    which INT,
    start_race INT,
    end_race INT,
    legs TEXT,
    payout REAL,
    PRIMARY KEY(date, city, which)
);

CREATE TABLE IF NOT EXISTS bets (
    race_id TEXT,
    bet TEXT,
    combo TEXT,
    payout REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bets_unique ON bets(race_id, bet, combo);

CREATE TABLE IF NOT EXISTS agf_snapshots (
    race_id TEXT,
    prog_no INT,
    captured_at TEXT,
    agf_pct REAL,
    agf_rank INT,
    ganyan_live REAL
);

CREATE TABLE IF NOT EXISTS predictions (
    race_id TEXT,
    prog_no INT,
    model_version TEXT,
    created_at TEXT,
    p_win REAL,
    agf_used REAL,
    PRIMARY KEY(race_id, prog_no, model_version)
);

CREATE TABLE IF NOT EXISTS weather_hourly (
    city TEXT,
    ts TEXT,
    precip_mm REAL,
    temp_c REAL,
    rh REAL,
    wind_kmh REAL,
    src TEXT,
    PRIMARY KEY(city, ts)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    source TEXT,
    target TEXT,
    status TEXT,
    http INT,
    bytes INT,
    fetched_at TEXT,
    PRIMARY KEY(source, target)
);

CREATE TABLE IF NOT EXISTS race_extra (
    race_id TEXT PRIMARY KEY,
    son800_raw TEXT,
    son800_s REAL,
    prize_1 REAL,
    source TEXT
);

CREATE TABLE IF NOT EXISTS runner_extra (
    race_id TEXT,
    horse_key TEXT,
    fark TEXT,
    gec_cikis TEXT,
    hp_result REAL,
    tjk_at_id INT,
    source TEXT,
    PRIMARY KEY(race_id, horse_key)
);

CREATE TABLE IF NOT EXISTS pools (
    date TEXT,
    city TEXT,
    bet TEXT,
    amount REAL,
    PRIMARY KEY(date, city, bet)
);

CREATE TABLE IF NOT EXISTS workouts (
    source TEXT,
    horse_key TEXT,
    horse_name TEXT,
    ext_horse_id TEXT,
    date TEXT,
    city TEXT,
    kind TEXT,
    jockey TEXT,
    kg REAL,
    d1600 REAL,
    d1400 REAL,
    d1200 REAL,
    d1000 REAL,
    d800 REAL,
    d600 REAL,
    d400 REAL,
    d200 REAL,
    effort TEXT,
    going TEXT,
    inner_outer TEXT,
    surface TEXT,
    PRIMARY KEY(source, horse_name, date, city, kind)
);

CREATE TABLE IF NOT EXISTS steward_notes (
    race_id TEXT,
    horse_name TEXT,
    horse_key TEXT,
    text TEXT,
    tags TEXT,
    PRIMARY KEY(race_id, horse_name)
);

CREATE TABLE IF NOT EXISTS ext_ratings (
    source TEXT,
    race_id TEXT,
    horse_key TEXT,
    name TEXT,
    value REAL,
    PRIMARY KEY(source, race_id, horse_key, name)
);

CREATE TABLE IF NOT EXISTS horse_ids (
    source TEXT,
    ext_id TEXT,
    horse_key TEXT,
    horse_name TEXT,
    PRIMARY KEY(source, ext_id)
);
"""


def init_db(path):
    """Initialize SQLite database idempotently and return a connection."""
    parent = os.path.dirname(str(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.executescript(SCHEMA_SQL)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(races)").fetchall()}
    for col in ("track_cond_raw", "track_cond"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE races ADD COLUMN {col} TEXT")
    conn.commit()
    return conn


def upsert_results(conn, parsed):
    """Upsert parsed results dict (races, runners, bets, altili) into SQLite."""
    cur = conn.cursor()
    for r in parsed.get("races", []):
        r_row = {"track_cond_raw": None, "track_cond": None, **r}
        cur.execute(
            """
            INSERT INTO races (
                race_id, date, city, race_no, post_time, yg_no, cls, breed,
                distance, surface, status, track_cond_raw, track_cond
            )
            VALUES (
                :race_id, :date, :city, :race_no, :post_time, :yg_no, :cls, :breed,
                :distance, :surface, :status, :track_cond_raw, :track_cond
            )
            ON CONFLICT(race_id) DO UPDATE SET
                date = excluded.date,
                city = excluded.city,
                race_no = excluded.race_no,
                post_time = COALESCE(excluded.post_time, races.post_time),
                yg_no = COALESCE(excluded.yg_no, races.yg_no),
                cls = COALESCE(excluded.cls, races.cls),
                breed = COALESCE(excluded.breed, races.breed),
                distance = COALESCE(excluded.distance, races.distance),
                surface = COALESCE(excluded.surface, races.surface),
                status = excluded.status,
                track_cond_raw = COALESCE(excluded.track_cond_raw, races.track_cond_raw),
                track_cond = COALESCE(excluded.track_cond, races.track_cond)
            """,
            r_row,
        )

    for run in parsed.get("runners", []):
        cur.execute(
            """
            INSERT INTO runners (
                race_id, horse_key, name, name_raw, age, sex, sire, dam,
                weight, jockey, owner, trainer, gate, hp,
                finish, time_s, ganyan, agf_close, agf_close_rank, scratched
            ) VALUES (
                :race_id, :horse_key, :name, :name_raw, :age, :sex, :sire, :dam,
                :weight, :jockey, :owner, :trainer, :gate, :hp,
                :finish, :time_s, :ganyan, :agf_close, :agf_close_rank, :scratched
            )
            ON CONFLICT(race_id, horse_key) DO UPDATE SET
                name = excluded.name,
                name_raw = excluded.name_raw,
                age = COALESCE(excluded.age, runners.age),
                sex = COALESCE(excluded.sex, runners.sex),
                sire = excluded.sire,
                dam = excluded.dam,
                weight = excluded.weight,
                jockey = excluded.jockey,
                owner = excluded.owner,
                trainer = excluded.trainer,
                gate = excluded.gate,
                hp = COALESCE(excluded.hp, runners.hp),
                finish = excluded.finish,
                time_s = excluded.time_s,
                ganyan = excluded.ganyan,
                agf_close = excluded.agf_close,
                agf_close_rank = excluded.agf_close_rank,
                scratched = excluded.scratched
            """,
            run,
        )

    for b in parsed.get("bets", []):
        cur.execute(
            """
            INSERT INTO bets (race_id, bet, combo, payout)
            VALUES (:race_id, :bet, :combo, :payout)
            ON CONFLICT(race_id, bet, combo) DO UPDATE SET
                payout = excluded.payout
            """,
            b,
        )

    for a in parsed.get("altili", []):
        row = dict(a)
        if not isinstance(row["legs"], str):
            row["legs"] = json.dumps(row["legs"])
        cur.execute(
            """
            INSERT INTO altili (date, city, which, start_race, end_race, legs, payout)
            VALUES (:date, :city, :which, :start_race, :end_race, :legs, :payout)
            ON CONFLICT(date, city, which) DO UPDATE SET
                start_race = excluded.start_race,
                end_race = excluded.end_race,
                legs = excluded.legs,
                payout = excluded.payout
            """,
            row,
        )
    conn.commit()


def upsert_program(conn, parsed):
    """Upsert parsed program dict (races, runners) into SQLite."""
    cur = conn.cursor()
    for r in parsed.get("races", []):
        r_row = {"track_cond_raw": None, "track_cond": None, **r}
        cur.execute(
            """
            INSERT INTO races (
                race_id, date, city, race_no, post_time, yg_no, cls, breed,
                distance, surface, status, track_cond_raw, track_cond
            )
            VALUES (
                :race_id, :date, :city, :race_no, :post_time, :yg_no, :cls, :breed,
                :distance, :surface, :status, :track_cond_raw, :track_cond
            )
            ON CONFLICT(race_id) DO UPDATE SET
                post_time = COALESCE(excluded.post_time, races.post_time),
                yg_no = COALESCE(excluded.yg_no, races.yg_no),
                cls = COALESCE(excluded.cls, races.cls),
                breed = COALESCE(excluded.breed, races.breed),
                distance = COALESCE(excluded.distance, races.distance),
                surface = COALESCE(excluded.surface, races.surface),
                status = CASE WHEN races.status IN ('result', 'cancelled') THEN races.status ELSE excluded.status END,
                track_cond_raw = COALESCE(excluded.track_cond_raw, races.track_cond_raw),
                track_cond = COALESCE(excluded.track_cond, races.track_cond)
            """,
            r_row,
        )

    for run in parsed.get("runners", []):
        row = dict(run)
        if row.get("son6") is not None and not isinstance(row["son6"], str):
            # Keep raw string or JSON if needed; spec §2.3 says raw text is stored or parsed
            pass
        cur.execute(
            """
            INSERT INTO runners (
                race_id, prog_no, horse_key, name, name_raw, age, sex, sire, dam,
                weight, jockey, owner, trainer, gate, hp,
                son6, kgs, s20, best_time_s, agf_close, agf_close_rank
            ) VALUES (
                :race_id, :prog_no, :horse_key, :name, :name_raw, :age, :sex, :sire, :dam,
                :weight, :jockey, :owner, :trainer, :gate, :hp,
                :son6_raw, :kgs, :s20, :best_time_s, :agf_pct, :agf_rank
            )
            ON CONFLICT(race_id, horse_key) DO UPDATE SET
                prog_no = excluded.prog_no,
                name = COALESCE(runners.name, excluded.name),
                name_raw = COALESCE(runners.name_raw, excluded.name_raw),
                age = COALESCE(runners.age, excluded.age),
                sex = COALESCE(runners.sex, excluded.sex),
                sire = COALESCE(runners.sire, excluded.sire),
                dam = COALESCE(runners.dam, excluded.dam),
                weight = COALESCE(runners.weight, excluded.weight),
                jockey = COALESCE(runners.jockey, excluded.jockey),
                owner = COALESCE(runners.owner, excluded.owner),
                trainer = COALESCE(runners.trainer, excluded.trainer),
                gate = COALESCE(runners.gate, excluded.gate),
                hp = COALESCE(runners.hp, excluded.hp),
                son6 = excluded.son6,
                kgs = excluded.kgs,
                s20 = excluded.s20,
                best_time_s = excluded.best_time_s,
                agf_close = COALESCE(runners.agf_close, excluded.agf_close),
                agf_close_rank = COALESCE(runners.agf_close_rank, excluded.agf_close_rank)
            """,
            row,
        )

    for a in parsed.get("altili", []):
        cur.execute(
            """
            INSERT INTO altili (date, city, which, start_race, end_race, legs, payout)
            VALUES (:date, :city, :which, :start_race, :end_race, NULL, NULL)
            ON CONFLICT(date, city, which) DO UPDATE SET
                start_race = COALESCE(excluded.start_race, altili.start_race),
                end_race = COALESCE(excluded.end_race, altili.end_race)
            """,
            a,
        )
    conn.commit()


def upsert_race_extra(conn, rows, commit=True):
    """Upsert race_extra records into SQLite."""
    cur = conn.cursor()
    for r in rows or []:
        row = {
            "son800_raw": None,
            "son800_s": None,
            "prize_1": None,
            "source": None,
            **r,
        }
        cur.execute(
            """
            INSERT INTO race_extra (race_id, son800_raw, son800_s, prize_1, source)
            VALUES (:race_id, :son800_raw, :son800_s, :prize_1, :source)
            ON CONFLICT(race_id) DO UPDATE SET
                son800_raw = COALESCE(excluded.son800_raw, race_extra.son800_raw),
                son800_s = COALESCE(excluded.son800_s, race_extra.son800_s),
                prize_1 = COALESCE(excluded.prize_1, race_extra.prize_1),
                source = COALESCE(excluded.source, race_extra.source)
            """,
            row,
        )
    if commit:
        conn.commit()


def upsert_runner_extra(conn, rows, commit=True):
    """Upsert runner_extra records into SQLite."""
    cur = conn.cursor()
    for r in rows or []:
        row = {
            "fark": None,
            "gec_cikis": None,
            "hp_result": None,
            "tjk_at_id": None,
            "source": None,
            **r,
        }
        cur.execute(
            """
            INSERT INTO runner_extra (
                race_id, horse_key, fark, gec_cikis, hp_result, tjk_at_id, source
            )
            VALUES (
                :race_id, :horse_key, :fark, :gec_cikis, :hp_result, :tjk_at_id, :source
            )
            ON CONFLICT(race_id, horse_key) DO UPDATE SET
                fark = COALESCE(excluded.fark, runner_extra.fark),
                gec_cikis = COALESCE(excluded.gec_cikis, runner_extra.gec_cikis),
                hp_result = COALESCE(excluded.hp_result, runner_extra.hp_result),
                tjk_at_id = COALESCE(excluded.tjk_at_id, runner_extra.tjk_at_id),
                source = COALESCE(excluded.source, runner_extra.source)
            """,
            row,
        )
    if commit:
        conn.commit()


def upsert_pools(conn, rows, commit=True):
    """Upsert daily pool amounts into SQLite."""
    cur = conn.cursor()
    for r in rows or []:
        cur.execute(
            """
            INSERT INTO pools (date, city, bet, amount)
            VALUES (:date, :city, :bet, :amount)
            ON CONFLICT(date, city, bet) DO UPDATE SET
                amount = excluded.amount
            """,
            r,
        )
    if commit:
        conn.commit()


def log_fetch(conn, source, target, status, http=None, nbytes=None, fetched_at=None, commit=True, **kw):
    """Insert or update a fetch_log entry."""
    if nbytes is None and "bytes" in kw:
        nbytes = kw["bytes"]
    if fetched_at is None:
        fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO fetch_log (source, target, status, http, bytes, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, target) DO UPDATE SET
            status = excluded.status,
            http = excluded.http,
            bytes = excluded.bytes,
            fetched_at = excluded.fetched_at
        """,
        (source, target, status, http, nbytes, fetched_at),
    )
    if commit:
        conn.commit()


def fetched_ok(conn, source, target):
    """Return True if (source, target) is marked status='ok' in fetch_log."""
    row = conn.execute(
        "SELECT status FROM fetch_log WHERE source = ? AND target = ?",
        (source, target),
    ).fetchone()
    return bool(row and row[0] == "ok")
