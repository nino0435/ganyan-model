"""SQLite database schema and upsert helpers."""
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
"""


def init_db(path):
    """Initialize SQLite database idempotently and return a connection."""
    parent = os.path.dirname(str(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def upsert_results(conn, parsed):
    """Upsert parsed results dict (races, runners, bets, altili) into SQLite."""
    cur = conn.cursor()
    for r in parsed.get("races", []):
        cur.execute(
            """
            INSERT INTO races (race_id, date, city, race_no, post_time, yg_no, cls, breed, distance, surface, status)
            VALUES (:race_id, :date, :city, :race_no, :post_time, :yg_no, :cls, :breed, :distance, :surface, :status)
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
                status = excluded.status
            """,
            r,
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
        cur.execute(
            """
            INSERT INTO races (race_id, date, city, race_no, post_time, yg_no, cls, breed, distance, surface, status)
            VALUES (:race_id, :date, :city, :race_no, :post_time, :yg_no, :cls, :breed, :distance, :surface, :status)
            ON CONFLICT(race_id) DO UPDATE SET
                post_time = COALESCE(excluded.post_time, races.post_time),
                yg_no = COALESCE(excluded.yg_no, races.yg_no),
                cls = COALESCE(excluded.cls, races.cls),
                breed = COALESCE(excluded.breed, races.breed),
                distance = COALESCE(excluded.distance, races.distance),
                surface = COALESCE(excluded.surface, races.surface),
                status = CASE WHEN races.status IN ('result', 'cancelled') THEN races.status ELSE excluded.status END
            """,
            r,
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
    conn.commit()
