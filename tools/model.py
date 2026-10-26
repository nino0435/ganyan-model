"""Build leak-free pre-race features, train a simple model, compare with the AGF favourite.

Usage: venv/bin/python model.py RUNS.pkl CSV_DIR [TEST_START=2026-04-01]
"""
import os, re, sys
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

RUNS, CSV_DIR = sys.argv[1], sys.argv[2]
TEST_START = pd.Timestamp(sys.argv[3] if len(sys.argv) > 3 else '2026-04-01')
TRAIN_START = pd.Timestamp('2025-01-01')  # earlier rows only seed horse/jockey history
UNIT_TL = 1.25  # altılı birim fiyatı 2026 (haber kaynağı); test dönemi tamamen 2026

df = pd.read_pickle(RUNS)
df = df[~df.scratched].copy()
df = df.sort_values(['date', 'city', 'race_no', 'finish']).reset_index(drop=True)
df['win'] = (df.finish == 1).astype(int)
df['field'] = df.groupby('race_id').finish.transform('size')
df['fpct'] = (df.finish - 1) / (df.field - 1).clip(lower=1)

# --- speed figure: time vs. reference median for the same track/surface/distance/breed (pre-test data only)
ref = df[(df.date < TEST_START) & df.time.notna()]
med_fine = ref.groupby(['city', 'surface', 'distance', 'breed']).time.agg(['median', 'size'])
med_coarse = ref.groupby(['surface', 'distance', 'breed']).time.median().rename('med_c')
df = df.join(med_fine, on=['city', 'surface', 'distance', 'breed']).join(med_coarse, on=['surface', 'distance', 'breed'])
df['ref_t'] = np.where(df['size'] >= 20, df['median'], df['med_c'])
df['sf'] = (df.ref_t - df.time) / df.ref_t * 1000
win_t = df[df.win == 1].groupby('race_id').time.min()
df['beaten'] = (df.time - df.race_id.map(win_t)) / df.distance * 1000
df['logodds'] = np.log(df.ganyan.clip(lower=1.01))

# --- horse history (a horse runs at most once per day, so shift(1) = strictly earlier days)
g = df.groupby('horse', sort=False)
df['h_n'] = g.cumcount()
for col, name in [('win', 'h_w'), ('finish', 'h_top3')]:
    s = df[col] if col == 'win' else (df.finish <= 3).astype(int)
    df[name] = s.groupby(df.horse).cumsum() - s
df['h_wr'] = (df.h_w + 0.3) / (df.h_n + 3)
df['h_t3r'] = (df.h_top3 + 0.9) / (df.h_n + 3)
for col in ['fpct', 'sf', 'beaten', 'logodds']:
    sh = g[col].shift(1)
    df[f'h_{col}_last'] = sh
    df[f'h_{col}_m3'] = sh.groupby(df.horse).transform(lambda s: s.rolling(3, min_periods=1).mean())
df['h_sf_best'] = g['sf'].shift(1).groupby(df.horse).cummax()
prev_date = g['date'].shift(1)
df['h_days'] = (df.date - prev_date).dt.days
df['h_dist_chg'] = df.distance - g['distance'].shift(1)
df['h_same_surf'] = (g['surface'].shift(1) == df.surface).astype(float).where(prev_date.notna())

# --- jockey / trainer prior win rates (counts up to the previous day)
for who, p in [('jockey', 'j'), ('trainer', 't')]:
    day = df.groupby([who, 'date']).win.agg(['size', 'sum']).groupby(level=0).cumsum()
    day_now = df.groupby([who, 'date']).win.agg(['size', 'sum'])
    prior = (day - day_now).rename(columns={'size': f'{p}_n', 'sum': f'{p}_w'})
    df = df.join(prior, on=[who, 'date'])
    df[f'{p}_wr'] = (df[f'{p}_w'] + 1) / (df[f'{p}_n'] + 10)

# --- race-relative features (known before the race)
rg = df.groupby('race_id')
for col in ['weight', 'hp', 'h_sf_m3', 'h_sf_best', 'j_wr', 'h_logodds_m3', 'h_fpct_m3']:
    df[f'{col}_rel'] = df[col] - rg[col].transform('mean')
    df[f'{col}_rk'] = rg[col].rank(ascending=col in ('h_logodds_m3', 'h_fpct_m3'), pct=True)
df['gate_frac'] = df.gate / df.field
df['arap'] = (df.breed == 'Arap').astype(int)
df['surf'] = df.surface.map({'Çim': 0, 'Kum': 1, 'Sentetik': 2})
df['sex_d'] = (df.sex == 'd').astype(int)
df['agf_share'] = df.agf_pct / rg.agf_pct.transform('sum')
df['log_agf'] = np.log(df.agf_share.clip(lower=1e-4))

BASE = ['h_n', 'h_wr', 'h_t3r', 'h_fpct_last', 'h_fpct_m3', 'h_sf_last', 'h_sf_m3', 'h_sf_best', 'h_beaten_last',
        'h_beaten_m3', 'h_logodds_last', 'h_logodds_m3', 'h_days', 'h_dist_chg', 'h_same_surf', 'j_n', 'j_wr', 't_n',
        't_wr', 'weight', 'hp', 'age', 'sex_d', 'gate', 'gate_frac', 'field', 'distance', 'surf', 'arap'] + \
       [c for c in df.columns if c.endswith('_rel') or c.endswith('_rk')]
WITH_AGF = BASE + ['agf_share', 'log_agf']

# --- evaluation set: races with full AGF, odds and a single winner
ok = rg.agf_pct.transform(lambda s: s.notna().all()) & rg.ganyan.transform(lambda s: s.notna().all()) \
     & (rg.win.transform('sum') == 1) & (df.field >= 4)
train = df[(df.date >= TRAIN_START) & (df.date < TEST_START) & ok]
test = df[(df.date >= TEST_START) & ok].copy()


def fit_predict(feats):
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.04, max_leaf_nodes=31,
                                       min_samples_leaf=60, l2_regularization=1.0, random_state=0)
    m.fit(train[feats], train.win)
    p = m.predict_proba(test[feats])[:, 1]
    return p / pd.Series(p, index=test.index).groupby(test.race_id).transform('sum').values


test['p_model'] = fit_predict(BASE)
test['p_model_agf'] = fit_predict(WITH_AGF)
test['p_agf'] = test.agf_share
inv = 1 / test.ganyan
test['p_odds'] = inv / inv.groupby(test.race_id).transform('sum')

METHODS = {'AGF favorisi': 'p_agf', 'Ganyan favorisi (son oran)': 'p_odds',
           'Model (AGF\'siz)': 'p_model', 'Model + AGF': 'p_model_agf'}
for col in METHODS.values():
    test[col + '_rk'] = test.groupby('race_id')[col].rank(ascending=False, method='first')

races = test.race_id.nunique()
print(f"Eğitim: {train.date.min().date()}..{train.date.max().date()}  {train.race_id.nunique()} koşu / {len(train)} at")
print(f"Test:   {test.date.min().date()}..{test.date.max().date()}  {races} koşu / {len(test)} at\n")
w = test[test.win == 1]
print(f"{'Yöntem':28} {'1.tercih kazandı':>17} {'ilk2':>6} {'ilk3':>6} {'ilk4':>6} {'log-loss':>9} {'ganyan ROI':>11}")
for name, col in METHODS.items():
    rk = w[col + '_rk']
    ll = -np.log(w[col].clip(lower=1e-6)).mean()
    top = test[test[col + '_rk'] == 1]
    roi = (top.win * top.ganyan).sum() / len(top) - 1
    print(f"{name:28} {(rk == 1).mean():16.1%} {(rk <= 2).mean():6.1%} {(rk <= 3).mean():6.1%} {(rk <= 4).mean():6.1%} {ll:9.4f} {roi:+10.1%}")

# bootstrap CI for accuracy difference vs AGF favourite (resample races)
rng = np.random.default_rng(0)
hit = {k: (w.set_index('race_id')[c + '_rk'] == 1).astype(float) for k, c in METHODS.items()}
base = hit['AGF favorisi'].values
for k in ["Model (AGF'siz)", 'Model + AGF', 'Ganyan favorisi (son oran)']:
    d = hit[k].values - base
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
    print(f"Fark ({k} − AGF favorisi): {d.mean():+.1%}  (%95 GA {np.percentile(bs, 2.5):+.1%} … {np.percentile(bs, 97.5):+.1%})")

print('\nIrka göre 1. tercih isabeti:')
for b, sub in w.groupby('breed'):
    print(f"  {b:8} {sub.race_id.nunique():5} koşu  " + "  ".join(f"{k} {(sub[c + '_rk'] == 1).mean():.1%}" for k, c in METHODS.items()))

print('\nDeğer bahsi (p × son oran ≥ eşik; son oranlar bahis anında bilinmez → iyimser):')
for col, name in [('p_model', "Model (AGF'siz)"), ('p_model_agf', 'Model + AGF')]:
    for th in (1.2, 1.5, 2.0):
        b = test[test[col] * test.ganyan >= th]
        if len(b):
            print(f"  {name:16} eşik {th}: {len(b):5} bahis, isabet {b.win.mean():5.1%}, ROI {(b.win * b.ganyan).sum() / len(b) - 1:+.1%}")


# --- altılı simulation on the official legs
def altili_table():
    out = []
    for fn in os.listdir(CSV_DIR):
        m = re.match(r'(\d{4}-\d{2}-\d{2})_(.+)\.csv$', fn)
        if not m or pd.Timestamp(m.group(1)) < TEST_START:
            continue
        cur = None
        for line in open(os.path.join(CSV_DIR, fn), encoding='utf-8-sig', errors='replace'):
            r = re.match(r'(\d+)\. Kosu :', line)
            if r:
                cur = int(r.group(1))
            for a in re.finditer(r"([12])\. 6'LI GANYAN\(([0-9,/]+)\) :([0-9.,]+) TL", line):
                legs = a.group(2).split('/')
                if len(legs) == 6 and cur:
                    out.append((m.group(1), m.group(2), a.group(1), cur, legs,
                                float(a.group(3).replace('.', '').replace(',', '.'))))
    return out


alts = altili_table()
print(f"\nAltılı simülasyonu (test dönemi, {len(alts)} altılı; her ayakta ilk k at; ikramiye birim başına, birim {UNIT_TL} TL varsayımı):")
by_race = {rid: grp for rid, grp in test.groupby('race_id')}
for k in (2, 3, 4):
    for name, col in [('AGF sırası', 'p_agf'), ('Model + AGF', 'p_model_agf'), ("Model (AGF'siz)", 'p_model')]:
        full = legs_sum = n = 0
        payout = 0.0
        for date, city, which, end, legs, pay in alts:
            rids = [f"{date}_{city}_{r}" for r in range(end - 5, end + 1)]
            if not all(r in by_race for r in rids):
                continue
            n += 1
            hits = 0
            for rid in rids:
                grp = by_race[rid]
                prog_winner = grp[grp.win == 1]
                hits += int((prog_winner[col + '_rk'] <= k).any())
            legs_sum += hits
            if hits == 6:
                full += 1
                payout += pay
        if n:
            cost = n * k ** 6 * UNIT_TL
            print(f"  k={k} {name:16}: {n} altılı, 6/6 tutan {full} ({full / n:.1%}), ort. ayak {legs_sum / n:.2f}, "
                  f"maliyet {cost:,.0f} TL, dönüş {payout:,.0f} TL, ROI {payout / cost - 1:+.0%}")

test.to_pickle(os.path.join(os.path.dirname(RUNS), 'test_predictions.pkl'))
