"""Parse TJK daily result CSVs into one horse-per-row table.

Usage: venv/bin/python parse_hist.py CSV_DIR OUT.pkl
"""
import os, re, sys
import pandas as pd

RACE_RE = re.compile(r'^(\d+)\. Kosu :')
TIME_RE = re.compile(r'^(?:(\d+):)?(\d+)\.(\d+)$')


def num(s):
    s = (s or '').strip().replace(',', '.')
    m = re.match(r'^-?\d+(?:\.\d+)?', s)
    return float(m.group(0)) if m else None


def weight(s):
    vals = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', (s or '').replace(',', '.'))]
    return sum(vals) if vals else None


def race_time(s):
    m = TIME_RE.match((s or '').strip())
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2)) + float('0.' + m.group(3))


def parse_file(path, date, city):
    text = open(path, encoding='utf-8-sig', errors='replace').read().replace('\r', '')
    rows, race = [], None
    for line in text.split('\n'):
        m = RACE_RE.match(line)
        if m:
            f = [x.strip() for x in line.split(';')]
            dist_i = next((i for i, x in enumerate(f) if re.fullmatch(r'\d+m', x)), None)
            race = {
                'race_no': int(m.group(1)),
                'cls': f[1] if len(f) > 1 else '',
                'breed': 'Arap' if 'Arap' in line else ('Ingiliz' if 'ngiliz' in line else 'Diger'),
                'distance': int(f[dist_i][:-1]) if dist_i is not None else None,
                'surface': f[dist_i + 1] if dist_i is not None and dist_i + 1 < len(f) else '',
            }
            continue
        if race is None or not re.match(r'\d+;', line):
            continue
        c = line.split(';')
        if len(c) < 15:
            continue
        scratched = 'Koşmaz' in c[1] or c[12].strip() == 'Koşmaz'
        agf = re.match(r'%\s*([\d.]+)\((\d+)\)', c[10].strip())
        yas = c[2].split()
        age = num(yas[0].rstrip('y')) if yas else None
        rows.append({
            'date': date, 'city': city, **race,
            'finish': int(c[0]), 'name': re.sub(r'\s*\(Koşmaz\)', '', c[1]).strip(),
            'age': age, 'sex': yas[-1] if len(yas) > 1 else '',
            'sire': c[3].strip(), 'dam': c[4].strip(), 'weight': weight(c[5]),
            'jockey': c[6].strip(), 'owner': c[7].strip(), 'trainer': c[8].strip(),
            'gate': num(c[9]), 'agf_pct': float(agf.group(1)) if agf else None,
            'agf_rank': int(agf.group(2)) if agf else None, 'hp': num(c[11]),
            'time': race_time(c[12]), 'ganyan': num(c[13]), 'scratched': scratched,
        })
    return rows


def main():
    src, out = sys.argv[1], sys.argv[2]
    rows = []
    for fn in sorted(os.listdir(src)):
        m = re.match(r'(\d{4}-\d{2}-\d{2})_(.+)\.csv$', fn)
        if m:
            rows += parse_file(os.path.join(src, fn), m.group(1), m.group(2))
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df['race_id'] = df['date'].dt.strftime('%Y-%m-%d') + '_' + df['city'] + '_' + df['race_no'].astype(str)
    df['birth_year'] = df['date'].dt.year - df['age']
    df['horse'] = df['sire'] + '|' + df['dam'] + '|' + df['birth_year'].astype('Int64').astype(str)
    df.to_pickle(out)
    run = df[~df.scratched]
    print(f"files={len(os.listdir(src))} rows={len(df)} runners={len(run)} races={run.race_id.nunique()} "
          f"days={df.date.nunique()} horses={run.horse.nunique()} range={df.date.min().date()}..{df.date.max().date()}")
    print('missing agf %:', round(run.agf_pct.isna().mean() * 100, 1), ' missing time %:', round(run.time.isna().mean() * 100, 1),
          ' missing ganyan %:', round(run.ganyan.isna().mean() * 100, 1))
    print(run.groupby('race_id').finish.apply(lambda s: (s == 1).sum()).value_counts().to_dict(), '<- winners per race')


if __name__ == '__main__':
    main()
