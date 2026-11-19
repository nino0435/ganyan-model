"""Bekçi: tahmin/akşam işleri durduysa GitHub issue açıp sahibine haber verir.

Zamanlayıcıdan (Cloud Scheduler) ve işin kendisinden bağımsız çalışır (GitHub'ın kendi cron'u).
Beklenen her tetik saati için o saatin etrafında bir çalışma var mı bakar; yoksa ya da çalışma
hata verdiyse `bekci` etiketli bir issue açar (sahibi anılır → e-posta/bildirim). Sorun kalkınca
issue'yu kendisi kapatır. Yalnız standart kütüphane + `gh`.
"""
import argparse
import base64
import datetime as dt
import json
import subprocess
import sys
from zoneinfo import ZoneInfo

IST = ZoneInfo("Europe/Istanbul")
OWNER = "nino0435"
REPO = "nino0435/ganyan-model"
LABEL = "bekci"

# Cloud Scheduler tetik saatleri (Europe/Istanbul) — ops/setup_cloud_scheduler.sh ile aynı olmalı.
V6_CANLI = "Ganyan V6 Canlı"
TAHMIN = V6_CANLI
SLOTS = [
    (V6_CANLI, 9, 40),
    (V6_CANLI, 13, 45),
    (V6_CANLI, 17, 34),
]
LOOKBACK = dt.timedelta(hours=5)  # 3 oturum arası ~4 saat olduğundan 5 saat geriye bak
PRE = dt.timedelta(minutes=5)  # tetikten biraz önce başlayan çalışma da sayılır
GRACE = dt.timedelta(minutes=20)  # tetikten sonra bu kadar içinde çalışma başlamış olmalı
BUDGET_WARN_MIN = 1700  # aylık 2000 dk sınırına yaklaşma uyarısı
# Cloud Scheduler'ın GitHub'ı tetiklemekte kullandığı ince ayarlı erişim anahtarının bitişi (.env.cron).
# Yenileyince burayı ve ops/setup_cloud_scheduler.sh'ı yeniden çalıştır. 7 gün kala uyarır.
PAT_EXPIRES = dt.date(2026, 12, 11)
PAT_WARN_DAYS = 7


def _parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def missing_slots(now, runs):
    """now: tz'li zaman; runs: [{workflowName, createdAt}]. Beklenip de başlamamış tetikler."""
    now = now.astimezone(IST)
    created = {}
    for r in runs:
        created.setdefault(r["workflowName"], []).append(_parse(r["createdAt"]))
    out = []
    for day in (now.date() - dt.timedelta(days=1), now.date()):
        for wf, h, m in SLOTS:
            s = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
            if s + GRACE >= now or s < now - LOOKBACK:
                continue
            if not any(s - PRE <= c <= s + GRACE for c in created.get(wf, [])):
                out.append(f"{wf}: {s:%d.%m %H:%M} tetiği hiç başlamadı")
    return out


def failed_runs(now, runs):
    out = []
    for r in runs:
        if r.get("conclusion") in ("failure", "timed_out") and now - _parse(r["createdAt"]) <= LOOKBACK:
            ts = _parse(r["createdAt"]).astimezone(IST)
            out.append(f"{r['workflowName']}: {ts:%d.%m %H:%M} çalışması {r['conclusion']}")
    return out


def find_problems(now, runs, budget_used=None):
    problems = missing_slots(now, runs) + failed_runs(now, runs)
    left = (PAT_EXPIRES - now.astimezone(IST).date()).days
    if left <= PAT_WARN_DAYS:
        problems.append(f"Zamanlayıcının GitHub erişim anahtarı {PAT_EXPIRES:%d.%m.%Y} tarihinde bitiyor ({left} gün kaldı)")
    if budget_used is not None and budget_used >= BUDGET_WARN_MIN:
        problems.append(f"Aylık Actions bütçesi {budget_used}/2000 dk'ya yaklaştı")
    return problems


def _gh(*args, check=True):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check).stdout


def _budget_used():
    try:
        out = _gh("api", f"repos/{REPO}/contents/budget.json", "-f", "ref=actions-state", "--jq", ".content")
        b = json.loads(base64.b64decode(out))
        now_month = dt.datetime.now(IST).strftime("%Y-%m")
        return b["used_min"] if b.get("month") == now_month else 0
    except Exception:  # noqa: BLE001 - bütçe okunamazsa uyarı üretme, diğer kontroller sürsün
        return None


def _open_issue():
    out = _gh("issue", "list", "--repo", REPO, "--label", LABEL, "--state", "open", "--json", "number", "--limit", "1")
    items = json.loads(out)
    return items[0]["number"] if items else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", dest="dry", help="issue açma/kapama yok, yalnız yaz")
    ap.add_argument("--selftest", action="store_true", help="bildirim yolunu denemek için sahte issue aç-kapat")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    if args.selftest:
        _gh("label", "create", LABEL, "--repo", REPO, "--color", "d73a4a", "--description", "Ganyan bekçi uyarısı", check=False)
        url = _gh("issue", "create", "--repo", REPO, "--label", LABEL, "--title", "Ganyan bekçi: bildirim testi",
                  "--body", f"@{OWNER} bu bir denemedir; bildirim ulaştıysa her şey hazır. Otomatik kapatılıyor.").strip()
        _gh("issue", "close", url, "--comment", "Deneme tamam.")
        print("selftest issue:", url)
        return 0

    runs = json.loads(_gh("run", "list", "--repo", REPO, "--limit", "100", "--json", "workflowName,createdAt,conclusion,status"))
    problems = find_problems(now, runs, None)
    if problems:
        print("SORUN:\n- " + "\n- ".join(problems))
    else:
        print("Her şey yolunda.")
    if args.dry:
        return 0

    num = _open_issue()
    if problems and num is None:
        _gh("label", "create", LABEL, "--repo", REPO, "--color", "d73a4a", "--description", "Ganyan bekçi uyarısı", check=False)
        body = f"@{OWNER} ganyan sistemi duruyor olabilir ({now.astimezone(IST):%d.%m.%Y %H:%M}):\n\n- " + "\n- ".join(problems)
        body += "\n\nKontrol: Cloud Scheduler işleri, GitHub Actions çalışmaları. Sorun kalkınca bu issue kendiliğinden kapanır."
        print("issue:", _gh("issue", "create", "--repo", REPO, "--label", LABEL, "--title", "Ganyan durmuş olabilir", "--body", body).strip())
    elif not problems and num is not None:
        _gh("issue", "close", str(num), "--repo", REPO, "--comment", "Sorun kalktı; çalışmalar normale döndü.")
        print("issue kapatıldı:", num)
    return 0


if __name__ == "__main__":
    sys.exit(main())
