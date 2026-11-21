"""Small real-LMS-index Spellfix quality probe; not a 100k-track benchmark."""
import argparse
from statistics import median
from time import perf_counter_ns
from poc.lms_index_probe import open_index

CASES = [
    ("daft pnk", "daft punk", "typo"),
    ("shiller", "schiller", "typo"),
    ("jamiroqai", "jamiroquai", "typo"),
    ("dead can danse", "dead can dance", "typo"),
    ("tatu", "tatu", "exact"),
    ("daft punk", "daft punk", "exact"),
    ("alpha will", "alphaville", "asr"),
    ("alfa will", "alphaville", "asr"),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=("9.1.0", "9.1", "9.2"))
    args = parser.parse_args()
    db = open_index(args.version)
    top1 = top5 = 0
    times = []
    try:
        for query, expected, group in CASES:
            start = perf_counter_ns()
            rows = db.execute("SELECT word FROM ps_spell_artist WHERE word MATCH ? LIMIT 5", (query,)).fetchall()
            times.append((perf_counter_ns() - start) / 1e6)
            names = [row[0] for row in rows]
            top1 += bool(names and names[0] == expected)
            top5 += expected in names
            print(f"{group} query={query!r} expected={expected!r} top1={names[0] if names else None!r}")
    finally:
        db.close()
    ordered = sorted(times)
    print(f"version={args.version} n={len(CASES)} top1={top1}/{len(CASES)} top5={top5}/{len(CASES)} "
          f"median_ms={median(times):.3f} p95_ms={ordered[int(.95*(len(ordered)-1))]:.3f}")

if __name__ == "__main__":
    main()
