"""Read-only verification of the isolated LMS 9.2 Perl plugin index."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from poc.lms_delta_probe import delta
from poc.lms_index_probe import load_extension
from poc.lms_poll_stage_probe import ROOT, TEST_DB, read_source
from poc.test_live_plugin_api import rpc


def main():
    directory = ROOT / "data" / "9.2" / "config" / "cache" / "PhoneticSearch"
    index_path = directory / "index.db"
    status_path = directory / "worker-status.json"
    if not TEST_DB.is_file() or not index_path.is_file():
        raise FileNotFoundError("Isolated LMS 9.2 source or plugin index missing")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    found = read_source(TEST_DB)
    with closing(sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)) as index:
        load_extension(index)
        integrity = index.execute("PRAGMA integrity_check").fetchone()[0]
        rows = index.execute("SELECT count(*) FROM ps_entity").fetchone()[0]
        schema = index.execute("SELECT value FROM ps_meta WHERE key='schema'").fetchone()[0]
        differences = delta(index, found)
    api_state = rpc("phoneticsearch", "status", "?")["result"]["state"]
    if (status.get("state") != "ready" or api_state != "ready" or schema != "3"
            or integrity != "ok" or differences or rows != len(found)):
        raise AssertionError({"status": status, "integrity": integrity,
                              "api_state": api_state, "schema": schema,
                              "rows": rows, "source": len(found),
                              "differences": differences[:10]})
    print(f"version=9.2 plugin_state=ready entities={rows} "
          f"source_differences=0 integrity={integrity} schema={schema} "
          f"mode={status['mode']}")


if __name__ == "__main__":
    main()
