"""P5 baseline only: deterministic stdlib similarity, explicitly not spellfix."""
from difflib import SequenceMatcher
from statistics import median
from time import perf_counter_ns
import unicodedata

NAMES = ["The Beatles", "Pink Floyd", "Rihanna", "Justin Bieber", "Beyoncé",
         "Rammstein", "AC/DC", "P!nk", "Die Ärzte", "Queen", "Love", "Live", "Alphaville"]
CASES = [("Bitels", "The Beatles", "typo"), ("Bietels", "The Beatles", "typo"),
         ("Pink Floid", "Pink Floyd", "typo"), ("Riana", "Rihanna", "typo"),
         ("Dschastin Biber", "Justin Bieber", "asr"),
         ("Beyonce", "Beyoncé", "diacritic"), ("Ramstein", "Rammstein", "typo"),
         ("ACDC", "AC/DC", "punctuation"), ("Pink", "P!nk", "punctuation"),
         ("Die Aerzte", "Die Ärzte", "transliteration"), ("Queen", "Queen", "exact"),
         ("alpha will", "Alphaville", "asr"), ("alfa will", "Alphaville", "asr")]

def normalize(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    return "".join(ch for ch in value if ch.isalnum() and not unicodedata.combining(ch))

def rank(query):
    q = normalize(query)
    return sorted(NAMES, key=lambda name: (-int(normalize(name) == q),
                  -SequenceMatcher(None, q, normalize(name)).ratio(), name))

def main():
    times = []
    top1 = top5 = 0
    for query, expected, group in CASES:
        start = perf_counter_ns()
        result = rank(query)
        times.append((perf_counter_ns() - start) / 1e6)
        top1 += result[0] == expected
        top5 += expected in result[:5]
        print(f"{group:15} {query:18} expected={expected:18} top1={result[0]}")
    ordered = sorted(times)
    print(f"BASELINE n={len(CASES)} top1={top1}/{len(CASES)} top5={top5}/{len(CASES)} "
          f"median_ms={median(times):.4f} p95_ms={ordered[int(.95*(len(ordered)-1))]:.4f}")

if __name__ == "__main__":
    main()
