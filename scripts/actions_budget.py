"""GitHub Actions dakika bütçesi yönetimi ve kapı kuralları (§3).

Şema (`state/budget.json`):
  {
    "month": "2026-11",
    "used_min": 0,
    "runs": [{"ts": "2026-11-09T10:02:15", "mode": "tahmin", "billed_min": 2}],
    "predictions_high_water": 0,
    "history": [...]
  }
"""
import argparse
import calendar
import copy
import datetime
import json
import math
import os
import sys
from zoneinfo import ZoneInfo

IST_TZ = ZoneInfo("Europe/Istanbul")

SOFT_LIMIT_MIN = 1400
PROJECTION_WARN_MIN = 1700
HARD_LIMIT_MIN = 1800
MONTH_QUOTA_MIN = 2000
TOLERANCE_MIN = 40

OVERHEAD_SEC_TAHMIN = 40
OVERHEAD_SEC_AKSAM = 90
OVERHEAD_BY_MODE = {
    "tahmin": OVERHEAD_SEC_TAHMIN,
    "aksam": OVERHEAD_SEC_AKSAM,
}

CRITICAL_SLOTS = ("10:00", "12:00", "14:30", "18:30")
OPTIONAL_SLOTS = ("09:00", "11:00", "13:00", "16:30", "20:30")
ALL_TAHMIN_SLOTS = ("09:00", "10:00", "11:00", "12:00", "13:00", "14:30", "16:30", "18:30", "20:30")


def _hm_to_minutes(hm_str):
    parts = hm_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _normalize_now(now):
    """now: datetime, time ya da 'HH:MM' / ISO string -> (datetime|None, day_minutes)."""
    if isinstance(now, datetime.datetime):
        dt = now.astimezone(IST_TZ) if now.tzinfo is not None else now
        return dt, dt.hour * 60 + dt.minute
    if isinstance(now, datetime.time):
        return None, now.hour * 60 + now.minute
    if isinstance(now, str):
        s = now.strip()
        if "T" in s or "-" in s:
            dt = datetime.datetime.fromisoformat(s)
            dt = dt.astimezone(IST_TZ) if dt.tzinfo is not None else dt
            return dt, dt.hour * 60 + dt.minute
        return None, _hm_to_minutes(s)
    raise TypeError(f"Desteklenmeyen zaman tipi: {type(now)!r}")


def ceil_billed_min(elapsed_sec):
    """İş süresini (saniye) dakikaya yukarı yuvarla; her iş en az 1 dk faturalanır."""
    if elapsed_sec is None or elapsed_sec <= 0:
        return 1
    return max(1, int(math.ceil(float(elapsed_sec) / 60.0)))


def classify_slot(now, tolerance_min=TOLERANCE_MIN):
    """Saat bilgisini en yakın tahmin cron saatine (±tolerance_min dk) yuvarla.

    Dönüş: (slot_hm | None, 'kritik' | 'istege_bagli')
    Eşit uzaklıkta erken olan cron seçilir (ALL_TAHMIN_SLOTS kronolojik sıralıdır).
    """
    _, now_min = _normalize_now(now)
    best_slot = min(ALL_TAHMIN_SLOTS, key=lambda s: abs(now_min - _hm_to_minutes(s)))
    diff = abs(now_min - _hm_to_minutes(best_slot))
    if diff > tolerance_min:
        return None, "istege_bagli"
    sinif = "kritik" if best_slot in CRITICAL_SLOTS else "istege_bagli"
    return best_slot, sinif


def default_budget_state(month_str):
    return {
        "month": month_str,
        "used_min": 0,
        "runs": [],
        "predictions_high_water": 0,
    }


def ensure_month(state, month_str):
    """Ay değiştiyse mevcut ayı history'ye taşıyıp yeni ay kaydını sıfırla.

    predictions_high_water ileri test boyunca korunur (ay başında sıfırlanmaz).
    """
    if not state:
        return default_budget_state(month_str)
    st = copy.deepcopy(state)
    st.setdefault("month", month_str)
    st.setdefault("used_min", 0)
    st.setdefault("runs", [])
    st.setdefault("predictions_high_water", 0)

    if st["month"] != month_str:
        hist = list(st.get("history", []))
        if st.get("runs") or st.get("used_min", 0) > 0:
            hist.append({
                "month": st["month"],
                "used_min": int(st.get("used_min", 0)),
                "runs": list(st.get("runs", [])),
            })
        st["month"] = month_str
        st["used_min"] = 0
        st["runs"] = []
        if hist:
            st["history"] = hist
    return st


def load_budget(path, month_str=None):
    """budget.json dosyasını oku; yoksa varsayılan durumu döndür."""
    if month_str is None:
        month_str = datetime.datetime.now(IST_TZ).strftime("%Y-%m")
    if not path or not os.path.exists(path):
        return default_budget_state(month_str)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return ensure_month(data, month_str)


def save_budget(path, state):
    """budget.json dosyasını atomik/düzenli biçimde kaydet."""
    parent = os.path.dirname(str(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def project_month_min(now, used_min):
    """Kalan gün/ay projeksiyonu: used_min / geçen_gün * ay_gün_sayısı."""
    dt, _ = _normalize_now(now)
    if dt is None:
        dt = datetime.datetime.now(IST_TZ)
    days_in_month = calendar.monthrange(dt.year, dt.month)[1]
    elapsed_days = max(1, dt.day)
    projected = float(used_min) / float(elapsed_days) * float(days_in_month)
    warn = projected > PROJECTION_WARN_MIN
    return {
        "projected_min": round(projected, 1),
        "elapsed_days": elapsed_days,
        "days_in_month": days_in_month,
        "warn": warn,
        "warning_text": (
            f"UYARI: aylık projeksiyon {projected:.0f} dk > {PROJECTION_WARN_MIN} dk "
            f"({used_min} dk / {elapsed_days} gün × {days_in_month} gün)"
            if warn
            else ""
        ),
    }


def karar(now, mode, month_state):
    """Bütçe kapısı kararı (§3).

    Parametreler:
      now: datetime, 'HH:MM' ya da ISO string (İstanbul saati)
      mode: 'tahmin' | 'aksam' | 'test'
      month_state: budget.json dict'i ya da doğrudan used_min (int)

    Dönüş dict:
      {
        "karar": "calis" | "atla",
        "allow": bool,
        "mode": mode,
        "slot": str | None,
        "sinif": "kritik" | "istege_bagli" | "aksam",
        "used_min": int,
        "error": bool,
        "reason": str,
      }
    """
    dt, _ = _normalize_now(now)
    if isinstance(month_state, (int, float)):
        used_min = int(month_state)
    elif isinstance(month_state, dict):
        st = month_state
        if dt is not None and st.get("month") and st.get("month") != dt.strftime("%Y-%m"):
            st = ensure_month(st, dt.strftime("%Y-%m"))
        used_min = int(st.get("used_min", 0))
    else:
        used_min = 0

    if mode == "aksam":
        return {
            "karar": "calis",
            "allow": True,
            "mode": mode,
            "slot": None,
            "sinif": "aksam",
            "used_min": used_min,
            "error": False,
            "reason": f"aksam her zaman çalışır (bütçe: {used_min} dk)",
        }

    slot, sinif = classify_slot(now)
    slot_label = slot or "cron-dışı"

    if used_min >= HARD_LIMIT_MIN:
        return {
            "karar": "atla",
            "allow": False,
            "mode": mode,
            "slot": slot,
            "sinif": sinif,
            "used_min": used_min,
            "error": True,
            "reason": f"bütçe doldu ({used_min} >= {HARD_LIMIT_MIN} dk); {mode} ({slot_label}) atlandı",
        }

    if used_min >= SOFT_LIMIT_MIN:
        if sinif == "kritik":
            return {
                "karar": "calis",
                "allow": True,
                "mode": mode,
                "slot": slot,
                "sinif": sinif,
                "used_min": used_min,
                "error": False,
                "reason": f"bütçe {used_min} dk ({SOFT_LIMIT_MIN}..{HARD_LIMIT_MIN - 1}): kritik çalışma ({slot_label}) izinli",
            }
        return {
            "karar": "atla",
            "allow": False,
            "mode": mode,
            "slot": slot,
            "sinif": sinif,
            "used_min": used_min,
            "error": False,
            "reason": f"bütçe koruma ({used_min} >= {SOFT_LIMIT_MIN} dk): isteğe bağlı çalışma ({slot_label}) atlandı",
        }

    return {
        "karar": "calis",
        "allow": True,
        "mode": mode,
        "slot": slot,
        "sinif": sinif,
        "used_min": used_min,
        "error": False,
        "reason": f"bütçe uygun ({used_min} < {SOFT_LIMIT_MIN} dk): {sinif} çalışma ({slot_label}) izinli",
    }


def record_run(
    state,
    ts,
    mode,
    elapsed_sec=None,
    billed_min=None,
    predictions_count=None,
    overhead_sec=None,
):
    """Çalışma sonunda faturalanan dakikayı ve predictions_high_water değerini güncelle.

    Betik süresi işin sonraki adımlarını (cache save, git commit/push, release upload)
    kapsamadığından billed_min doğrudan verilmemişse mode'a göre OVERHEAD_SEC_* eklenir.
    """
    if isinstance(ts, datetime.datetime):
        dt = ts.astimezone(IST_TZ) if ts.tzinfo is not None else ts
        ts_str = dt.strftime("%Y-%m-%dT%H:%M:%S")
        month_str = dt.strftime("%Y-%m")
    else:
        ts_str = str(ts)
        month_str = ts_str[:7]

    st = ensure_month(state, month_str)
    if billed_min is not None:
        b_min = int(billed_min)
    else:
        extra = OVERHEAD_BY_MODE.get(mode, 0) if overhead_sec is None else float(overhead_sec)
        total_sec = (float(elapsed_sec) if elapsed_sec is not None else 0.0) + extra
        b_min = ceil_billed_min(total_sec)
    st["used_min"] = int(st.get("used_min", 0)) + b_min
    st.setdefault("runs", []).append({
        "ts": ts_str,
        "mode": mode,
        "billed_min": b_min,
    })
    if predictions_count is not None:
        st["predictions_high_water"] = max(int(st.get("predictions_high_water", 0)), int(predictions_count))
    return st


def format_budget_summary(state, now=None):
    """Özet satırı üret (projeksiyon > 1700 ise UYARI içerir)."""
    if now is None:
        now = datetime.datetime.now(IST_TZ)
    used = int(state.get("used_min", 0))
    proj = project_month_min(now, used)
    msg = (
        f"bütçe {state.get('month', '?')}: {used}/{HARD_LIMIT_MIN} dk "
        f"(kota {MONTH_QUOTA_MIN}, projeksiyon {proj['projected_min']:.0f} dk, "
        f"high_water={state.get('predictions_high_water', 0)})"
    )
    if proj["warn"]:
        msg += f" — {proj['warning_text']}"
    return msg


def main(argv=None):
    ap = argparse.ArgumentParser(description="GitHub Actions dakika bütçesi aracı")
    ap.add_argument("action", nargs="?", default="summary", choices=["check", "record", "summary"])
    ap.add_argument("--state", default="state/budget.json", help="budget.json dosya yolu")
    ap.add_argument("--mode", default="tahmin", choices=["tahmin", "aksam", "test"])
    ap.add_argument("--now", help="YYYY-MM-DDTHH:MM(:SS) İstanbul saati")
    ap.add_argument("--elapsed-sec", type=float, default=None)
    ap.add_argument("--billed-min", type=int, default=None)
    ap.add_argument("--predictions-count", type=int, default=None)
    args = ap.parse_args(argv)

    now = datetime.datetime.fromisoformat(args.now) if args.now else datetime.datetime.now(IST_TZ)
    st = load_budget(args.state, month_str=now.strftime("%Y-%m"))

    if args.action == "check":
        res = karar(now, args.mode, st)
        if res["error"]:
            print(f"::error::{res['reason']}")
        print(f"{res['karar']}: {res['reason']}")
        return 0

    if args.action == "record":
        st = record_run(
            st,
            now,
            args.mode,
            elapsed_sec=args.elapsed_sec,
            billed_min=args.billed_min,
            predictions_count=args.predictions_count,
        )
        save_budget(args.state, st)
        print(format_budget_summary(st, now=now))
        return 0

    print(format_budget_summary(st, now=now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
