"""Read-only check of change-time columns in the isolated LMS 9.2 database."""
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "9.2" / "config" / "cache" / "library.db"


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    with sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True) as db:
        for table in ("tracks", "albums", "contributors", "genres"):
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            indexes = [row[1] for row in db.execute(f"PRAGMA index_list({table})")]
            print(f"{table}: time_columns={sorted(columns & {'timestamp', 'added_time', 'updated_time'})} "
                  f"updated_time_index={any('updated_time' in index for index in indexes)}")
            if "updated_time" in columns:
                count, nulls, min_value, max_value = db.execute(
                    f"SELECT count(*),sum(updated_time IS NULL),min(updated_time),max(updated_time) "
                    f"FROM {table}").fetchone()
                print(f"{table}: rows={count} updated_time_null={nulls} "
                      f"updated_time_min={min_value} updated_time_max={max_value}")


if __name__ == "__main__":
    main()
