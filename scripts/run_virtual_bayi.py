#!/usr/bin/env python3
"""Sanal ganyan bayisi — canlı veriyle 13 kumarbazı paper-trade eder (gerçek para yok).

İki iz, paralel:
  - Track A ("A_kapanis_v10"): kapanışa yakın AGF + v10_hlb (canlı pipeline'ın zaten ürettiği,
    due_max_min<=8dk penceresindeki predictions_v5 satırları kullanılır; ek model çağrısı yok).
  - Track B ("B_sabah_fund06"): günün ilk AGF'si + fund_06 (forward_v5.py --due-max-min çok büyük
    verilerek ayrı bir çıktı db'sine (--out) tek seferlik, günün tüm koşuları için erken tahmin
    yazdırılır; bu, normal canlı akıştaki predictions_v5'i ETKİLEMEZ).

Alt komutlar:
  place-b  : sabah erken fund_06 koşusunu (forward_v5.py) çalıştırıp 13 kumarbazın seçimini kaydet.
  place-a  : günün (zaten üretilmiş) v10_hlb kapanış tahminlerinden 13 kumarbazın seçimini kaydet.
  settle   : sonuçlanmış koşuların bekleyen bahislerini gerçek ödemeyle kapat.
  report   : state/VIRTUAL_BAYI.md yaz (her kumarbaz x iz: kasa, bahis sayısı, isabet).

Kumarbaz kuralları: docs/KUMARBAZ_BULGULAR.md (Altılı Ayşe / Kuponcu Kemal hariç — bkz. oradaki not).
"""
import argparse
import datetime
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ganyan.kumarbaz_personas import (  # noqa: E402
    BANK0, BASE, BET, MIN_BET, PERSONAS, UNIT,
    DayRace, combos_of, paid, parse_combo, stake_tl,
)

VB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vb_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track TEXT NOT NULL,
    persona TEXT NOT NULL,
    race_id TEXT NOT NULL,
    bet_type TEXT NOT NULL,
    combo TEXT NOT NULL,
    stake_tl REAL NOT NULL,
    p_model REAL,
    p_agf REAL,
    placed_at TEXT NOT NULL,
    settled INTEGER NOT NULL DEFAULT 0,
    win INTEGER,
    payout_tl REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vb_bets_unique ON vb_bets(track, persona, race_id, bet_type);
"""


def ensure_schema(conn):
    conn.executescript(VB_SCHEMA_SQL)
    conn.commit()


def _open(path):
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ----------------------------------------------------------------------------- günü kur
def _field(main_conn, date_str):
    """{race_id: [(prog_no, horse_key)]}: iptal olmayan, çekilmemiş koşucular."""
    rows = main_conn.execute(
        """
        SELECT ru.race_id, ru.prog_no, ru.horse_key
        FROM runners ru JOIN races r USING(race_id)
        WHERE r.date = ? AND COALESCE(r.status, '') != 'cancelled' AND COALESCE(ru.scratched, 0) = 0
          AND ru.prog_no IS NOT NULL
        """,
        (date_str,),
    ).fetchall()
    out = {}
    for rid, prog_no, hk in rows:
        out.setdefault(rid, []).append((int(prog_no), hk))
    return out


def _agf_snapshot_map(main_conn, date_str, which="max"):
    """{(race_id, prog_no): (agf_pct, ganyan_live)} — which='max': en son (kapanışa yakın), 'min': en ilk (sabah)."""
    agg = "MAX" if which == "max" else "MIN"
    rows = main_conn.execute(
        f"""
        SELECT s.race_id, s.prog_no, s.agf_pct, s.ganyan_live
        FROM agf_snapshots s
        JOIN (
            SELECT race_id, prog_no, {agg}(captured_at) AS cap
            FROM agf_snapshots s2 JOIN races r2 USING(race_id)
            WHERE r2.date = ?
            GROUP BY race_id, prog_no
        ) m ON m.race_id = s.race_id AND m.prog_no = s.prog_no AND m.cap = s.captured_at
        """,
        (date_str,),
    ).fetchall()
    return {(rid, int(pno)): (agf, gl) for rid, pno, agf, gl in rows}


def build_day(main_conn, pred_conn, date_str, model_version, snap_which):
    """DayRace listesi: predictions_v5 (pred_conn, model_version) + agf_snapshots (main_conn, snap_which)."""
    field = _field(main_conn, date_str)
    snaps = _agf_snapshot_map(main_conn, date_str, which=snap_which)
    preds = pred_conn.execute(
        "SELECT race_id, prog_no, p_win FROM predictions_v5 WHERE model_version = ? AND race_id LIKE ?",
        (model_version, f"{date_str}%"),
    ).fetchall()
    p_by = {(rid, int(pno)): float(p) for rid, pno, p in preds}

    races_meta = main_conn.execute(
        "SELECT race_id, post_time FROM races WHERE date = ? ORDER BY post_time, race_id", (date_str,)
    ).fetchall()

    day = []
    for rid, _post_time in races_meta:
        progs = sorted(p[0] for p in field.get(rid, []))
        if not progs:
            continue
        p_arr, agf_raw, odds = [], [], []
        for pno in progs:
            p_arr.append(p_by.get((rid, pno), float("nan")))
            agf, gl = snaps.get((rid, pno), (float("nan"), float("nan")))
            agf_raw.append(agf if agf is not None else float("nan"))
            odds.append(gl if gl is not None else float("nan"))
        s = sum(x for x in agf_raw if x == x and x > 0)   # NaN-safe toplam
        agfp = [(x / s if (s and x == x) else float("nan")) for x in agf_raw]
        day.append(DayRace(rid, progs, p_arr, agfp, odds))
    return day


# ----------------------------------------------------------------------------- place
def _insert_picks(conn, track, picks, now_iso, replace):
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    n = 0
    for pk in picks:
        cur = conn.execute(
            f"""
            {verb} INTO vb_bets (track, persona, race_id, bet_type, combo, stake_tl, p_model, p_agf, placed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (track, pk.persona, pk.race_id, pk.bet_type, json.dumps(list(pk.combo)),
             BASE, pk.p, pk.agfp, now_iso),
        )
        n += cur.rowcount
    conn.commit()
    return n


def _track_has_bets(conn, track, date_str):
    """Bu izde, bu güne ait (race_id tarihle başlar; çifte 'a|b' da öyle) herhangi bir bahis var mı?"""
    return conn.execute(
        "SELECT 1 FROM vb_bets WHERE track = ? AND race_id LIKE ? LIMIT 1", (track, f"{date_str}%")
    ).fetchone() is not None


def cmd_place_b(args):
    """Sabah erken fund_06 tahminini (ayrı --out db'ye) üretip Track B'nin bahislerini kaydet.

    Günde yalnız bir kez: o güne ait Track B bahsi varsa hiçbir şey yapmaz (ikinci çalışma tahmini kaydırıp
    "sabah erken tek tahmin" varsayımını bozuyordu).
    """
    guard_conn = _open(args.state_db)
    ensure_schema(guard_conn)
    try:
        if _track_has_bets(guard_conn, "B_sabah_fund06", args.date):
            print(f"[virtual_bayi] place-b: {args.date} için Track B bahisleri zaten yerleştirilmiş, atlandı")
            return
    finally:
        guard_conn.close()
    morning_db = args.morning_db
    cmd = [
        sys.executable, str(REPO / "scripts" / "forward_v5.py"),
        "--date", args.date, "--db", args.main_db, "--out", morning_db,
        "--models", "fund_06", "--model-cache-dir", args.model_cache_dir,
        "--due-max-min", "100000000", "--once",
    ]
    print(f"[virtual_bayi] sabah fund_06 çalıştırılıyor: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=False, cwd=str(REPO))

    main_conn = _open(args.main_db)
    pred_conn = _open(morning_db)
    state_conn = _open(args.state_db)
    ensure_schema(state_conn)
    try:
        day = build_day(main_conn, pred_conn, args.date, "fund_06", snap_which="min")
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        total = 0
        for _name, _kind, fn, _bet_type in PERSONAS:
            total += _insert_picks(state_conn, "B_sabah_fund06", fn(day), now_iso, replace=False)
        print(f"[virtual_bayi] place-b: {len(day)} koşu, {total} yeni bahis (Track B)")
    finally:
        main_conn.close()
        pred_conn.close()
        state_conn.close()


def cmd_place_a(args):
    """Günün (zaten üretilmiş) v10_hlb kapanış tahminlerinden Track A'nın bahislerini kaydet."""
    main_conn = _open(args.main_db)
    state_conn = _open(args.state_db)
    ensure_schema(state_conn)
    try:
        day = build_day(main_conn, state_conn, args.date, "v10_hlb", snap_which="max")
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        total = 0
        for _name, _kind, fn, _bet_type in PERSONAS:
            total += _insert_picks(state_conn, "A_kapanis_v10", fn(day), now_iso, replace=False)
        print(f"[virtual_bayi] place-a: {len(day)} koşu, {total} yeni bahis (Track A)")
    finally:
        main_conn.close()
        state_conn.close()


# ----------------------------------------------------------------------------- settle
def _race_result(conn, race_id):
    row = conn.execute("SELECT status FROM races WHERE race_id = ?", (race_id,)).fetchone()
    return row[0] if row else None


def _ganyan_outcome(conn, race_id, prog_no):
    row = conn.execute(
        "SELECT finish, ganyan, COALESCE(scratched, 0) FROM runners WHERE race_id = ? AND prog_no = ?",
        (race_id, prog_no),
    ).fetchone()
    if row is None:
        return None
    finish, ganyan, scratched = row
    if scratched:
        return "void"
    if finish is None:
        return None
    return (int(finish) == 1, float(ganyan) if ganyan else 0.0)


def _bet_rows(conn, race_id, bet_name):
    rows = conn.execute("SELECT combo, payout FROM bets WHERE race_id = ? AND bet = ?", (race_id, bet_name)).fetchall()
    out = []
    for combo, payout in rows:
        pos = parse_combo(combo)
        if pos is None or not payout or payout <= 0:
            continue
        if bet_name == "PLASE" and len(pos) != 1:
            continue
        out.append((pos, float(payout)))
    return out


def _cifte_rows(conn, race_id_b):
    """race_id_b'nin ÇİFTE ödeme satırları (ilk ayak numarası doğrulanarak)."""
    _date, city, no_s = race_id_b.rsplit("_", 2)
    no = int(no_s)
    rows = conn.execute("SELECT combo, payout FROM bets WHERE race_id = ? AND bet LIKE '%. ÇİFTE'", (race_id_b,)).fetchall()
    out = []
    for combo, payout in rows:
        bet_label = conn.execute(
            "SELECT bet FROM bets WHERE race_id = ? AND combo = ? AND bet LIKE '%. ÇİFTE' LIMIT 1", (race_id_b, combo)
        ).fetchone()
        if not bet_label:
            continue
        try:
            leg_no = int(bet_label[0].split(".")[0])
        except ValueError:
            continue
        if leg_no + 1 != no:
            continue
        pos = parse_combo(combo)
        if pos is None or not payout or payout <= 0:
            continue
        out.append((pos, float(payout)))
    return out


def _settle_one(main_conn, bet_type, race_id, combo):
    """Tek bir bekleyen bahsi çöz: (win, payout_oran) ya da None (henüz sonuçlanmadı) ya da 'void'."""
    if bet_type == "cifte":
        rid_a, rid_b = race_id.split("|")
        if _race_result(main_conn, rid_a) != "result" or _race_result(main_conn, rid_b) != "result":
            return None
        rows = _cifte_rows(main_conn, rid_b)
        got = paid(rows, tuple(combo))
        return (got > 0, got)

    if _race_result(main_conn, race_id) != "result":
        return None

    if bet_type == "ganyan":
        outcome = _ganyan_outcome(main_conn, race_id, combo[0])
        if outcome is None:
            return None
        if outcome == "void":
            return "void"
        win, odds = outcome
        return (win, odds if win else 0.0)

    bet_name = BET[bet_type]
    rows = _bet_rows(main_conn, race_id, bet_name)
    if not rows:
        return "void"   # bu bahis türü bu koşuda hiç oynatılmamış
    cs = combos_of(bet_type, combo)
    got = sum(paid(rows, c) for c in cs) / UNIT.get(bet_name, 1.0)
    return (got > 0, got / len(cs))


SEQUENTIAL = {name: kind for name, kind, *_ in PERSONAS if kind != "flat"}   # Bitik (bitik), Selin (kelly)


def _replay_sequential(main_conn, state_conn):
    """Bitik (kaybedince katla) ve Selin (çeyrek Kelly): bahis tutarı kasa/seriye bağlı, yani sırayla belli olur.

    Bahisler koşu saatine göre dizilip her çağrıda baştan oynatılır (sim ile aynı kural); ilk sonuçlanmamış
    bahiste durur, böylece tutar hiçbir zaman henüz bilinmeyen bir sonuca dayanmaz.
    """
    n_settled = n_void = 0
    for track, persona in state_conn.execute("SELECT DISTINCT track, persona FROM vb_bets").fetchall():
        kind = SEQUENTIAL.get(persona)
        if kind is None:
            continue
        rows = state_conn.execute(
            "SELECT id, bet_type, race_id, combo, p_model, p_agf, settled FROM vb_bets WHERE track = ? AND persona = ?",
            (track, persona),
        ).fetchall()
        post = {rid: (main_conn.execute("SELECT post_time FROM races WHERE race_id = ?", (rid,)).fetchone() or ("",))[0] or ""
                for rid in {r[2] for r in rows}}
        rows.sort(key=lambda r: (r[2][:10], post[r[2]], r[0]))
        bank, streak, day, open_, spent = BANK0, 0, None, BANK0, 0.0
        for bet_id, bet_type, race_id, combo_json, p, agf, was_settled in rows:
            if _race_result(main_conn, race_id) == "cancelled":
                res = "void"
            else:
                res = _settle_one(main_conn, bet_type, race_id, json.loads(combo_json))
            if res is None:
                break
            if race_id[:10] != day:
                day, open_, spent = race_id[:10], bank, 0.0
            stake = 0.0
            if res != "void":
                stake = min(stake_tl(kind, bank, float(p or 0.0), float(agf or 0.0), streak, open_, spent), bank)
            if res == "void" or stake < MIN_BET:
                state_conn.execute(
                    "UPDATE vb_bets SET settled = 1, win = NULL, payout_tl = NULL, stake_tl = ? WHERE id = ?",
                    (BASE if res == "void" else 0.0, bet_id),
                )
                n_void += 0 if was_settled else 1
                continue
            win, odds_ret = res
            payout = stake * odds_ret if win else 0.0
            state_conn.execute(
                "UPDATE vb_bets SET settled = 1, win = ?, payout_tl = ?, stake_tl = ? WHERE id = ?",
                (int(win), payout, stake, bet_id),
            )
            bank += payout - stake
            spent += stake
            streak = 0 if win else streak + 1
            n_settled += 0 if was_settled else 1
    state_conn.commit()
    return n_settled, n_void


def cmd_settle(args):
    main_conn = _open(args.main_db)
    state_conn = _open(args.state_db)
    ensure_schema(state_conn)
    try:
        pending = [
            r for r in state_conn.execute(
                "SELECT id, bet_type, race_id, combo, stake_tl, persona FROM vb_bets WHERE settled = 0"
            ).fetchall()
            if r[5] not in SEQUENTIAL
        ]
        n_settled = n_void = 0
        for bet_id, bet_type, race_id, combo_json, stake, _persona in pending:
            combo = json.loads(combo_json)
            res = _settle_one(main_conn, bet_type, race_id, combo)
            if res is None:
                continue
            if res == "void":
                state_conn.execute("UPDATE vb_bets SET settled = 1, win = NULL, payout_tl = NULL WHERE id = ?", (bet_id,))
                n_void += 1
                continue
            win, odds_ret = res
            payout = stake * odds_ret if win else 0.0
            state_conn.execute(
                "UPDATE vb_bets SET settled = 1, win = ?, payout_tl = ? WHERE id = ?",
                (int(win), payout, bet_id),
            )
            n_settled += 1
        state_conn.commit()
        s2, v2 = _replay_sequential(main_conn, state_conn)
        n_settled += s2
        n_void += v2
        print(f"[virtual_bayi] settle: {n_settled} bahis sonuçlandı, {n_void} boş (oynanmamış) sayıldı")
    finally:
        main_conn.close()
        state_conn.close()


# ----------------------------------------------------------------------------- report
def _ledger(conn, track, persona):
    rows = conn.execute(
        """
        SELECT settled, win, stake_tl, payout_tl FROM vb_bets
        WHERE track = ? AND persona = ? ORDER BY placed_at, id
        """,
        (track, persona),
    ).fetchall()
    bank = BANK0
    n_settled = n_pending = n_void = n_hit = 0
    for settled, win, stake, payout in rows:
        if not settled:
            n_pending += 1
            continue
        if win is None:
            n_void += 1
            continue
        n_settled += 1
        if win:
            n_hit += 1
        bank += (payout or 0.0) - stake
    return dict(bank=bank, n_settled=n_settled, n_pending=n_pending, n_void=n_void, n_hit=n_hit)


def cmd_report(args):
    state_conn = _open(args.state_db)
    ensure_schema(state_conn)
    try:
        lines = ["# Sanal Bayi — Canlı Kumarbaz Defteri\n"]
        lines.append(
            "> Gerçek para yok. 13 kumarbaz (Altılı Ayşe / Kuponcu Kemal hariç — bkz. "
            "`docs/KUMARBAZ_BULGULAR.md`), iki paralel izde: **Track A** kapanışa yakın AGF + "
            "`v10_hlb`, **Track B** sabah erken AGF + `fund_06`. Kasa 10.000 TL, bahis 50 TL. "
            "Kurallar `ganyan/kumarbaz_personas.py`'de, geriye dönük simülasyonla birebir aynı. "
            "**Not:** Bitik Bilal (kaybedince bahis ikiye katlanır) ve Stratejik Selin (çeyrek Kelly) bahis tutarını "
            "sonuçlanma sırasına göre belirler; bekleyen bahislerde tutar henüz belli değildir (gösterilen 50 TL "
            "yer tutucudur). Selin'in Kelly'nin elediği bahisleri \"Boş\" sütununa düşer.\n"
        )
        for track, label in (("A_kapanis_v10", "Track A (kapanış + v10_hlb)"), ("B_sabah_fund06", "Track B (sabah + fund_06)")):
            lines.append(f"\n## {label}\n")
            lines.append("| Kumarbaz | Kasa (TL) | Sonuçlanan | İsabet | Bekleyen | Boş (oynanmamış) |")
            lines.append("|---|---:|---:|---:|---:|---:|")
            for name, *_ in PERSONAS:
                led = _ledger(state_conn, track, name)
                hit = f"{led['n_hit'] / led['n_settled']:.1%}" if led["n_settled"] else "—"
                lines.append(
                    f"| {name} | {led['bank']:,.0f} | {led['n_settled']} | {hit} | "
                    f"{led['n_pending']} | {led['n_void']} |"
                )
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[virtual_bayi] yazıldı: {out_path}")
    finally:
        state_conn.close()


def build_arg_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main-db", default="data/ganyan.db")
    ap.add_argument("--state-db", default="state/forward_v5.db")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("place-b", help="Sabah erken fund_06 + Track B bahislerini yerleştir")
    p.add_argument("--date", required=True)
    p.add_argument("--morning-db", default="state/vb_morning.db")
    p.add_argument("--model-cache-dir", default="data/forward_models")
    p.set_defaults(func=cmd_place_b)

    p = sub.add_parser("place-a", help="Kapanış v10_hlb + Track A bahislerini yerleştir")
    p.add_argument("--date", required=True)
    p.set_defaults(func=cmd_place_a)

    p = sub.add_parser("settle", help="Bekleyen bahisleri sonuçlanmış koşularla kapat")
    p.set_defaults(func=cmd_settle)

    p = sub.add_parser("report", help="state/VIRTUAL_BAYI.md yaz")
    p.add_argument("--out", default="state/VIRTUAL_BAYI.md")
    p.set_defaults(func=cmd_report)
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
