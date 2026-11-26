# PhoneticSearch for Lyrion Music Server

<p align="center"><img src="src/HTML/EN/plugins/PhoneticSearch/html/icon.png" alt="PhoneticSearch" width="160"></p>

## Installation through the LMS plugin manager

Requires **Lyrion Music Server 9.1.0 or later** on a supported platform. The LMS repository feed URL is:

```text
https://raw.githubusercontent.com/oweitman/LMS-PhoneticSearch/main/public.xml
```

1. Open **Settings > Plugins** in the LMS web interface.
2. Under **Additional repositories** at the bottom of the page, add the URL above and save.
3. Reload the page if needed, select **PhoneticSearch** from the available plugins, and apply the installation.
4. Restart LMS when prompted. Open the plugin's **Settings** link and wait for the index state to become `ready`.

The following architectures are currently supported:

- linux-aarch64
- linux-armv7
- linux-x86_64
- macos-arm64
- macos-x86_64
- windows-x86_64

The feed is published only after all six binary checks pass. If your platform is not yet validated as a complete LMS runtime, use a separate test server first. See [compatibility](docs/compatibility.md) and the [manual test installation guide](docs/test-installation.md).

LMS 9.1.0 is the declared minimum version. The complete plugin has so far been tested only with LMS 9.2.0 on Linux x86_64; the LMS 9.1 plugin runtime remains unverified.

PhoneticSearch adds a read-only JSON-RPC search for artists, albums, tracks and genres. It combines exact, normalized, alias, prefix and phonetic matching. Artist names, album titles and track titles also support words and phrases from the middle of a name, including phonetic variants of phrases up to four words. Phonetic partial matching for artists and albums requires at least two query words; exact partial matching also works for one word. For example, speech recognition may turn **Alphaville** into `alpha will` or `alfa will`; both returned Alphaville as the first artist hit in the LMS 9.2 test library. The plugin does not replace the standard LMS search screen.

The plugin maintains its own SQLite index under the LMS cache. It reads `library.db` without adding triggers or changing LMS Core. A separate worker reconciles the index at startup, after LMS scan completion, after targeted album or track rescans, or when an administrator requests verification or rebuilding. The plugin does not poll the library while idle. A full comparison after each scan catches deletions and name changes without an update timestamp. Temporary timers only wait for an active scan or worker and retry errors; workers do not overlap. During an LMS scan, searches pause. Results are checked against current library names before they are returned. Changes made directly to the LMS database outside a scan require a manual rebuild or server restart.

## Commands

Send commands to LMS at `http://LMS_HOST:9000/jsonrpc.js` using the `slim.request` method. The first item in `params` is the player ID; use an empty string for these server commands.

| Command array                                                      | Purpose                                                       |
| ------------------------------------------------------------------ | ------------------------------------------------------------- |
| `["phoneticsearch", "status", "?"]`                                | Get index and worker status.                                  |
| `["phoneticsearch", "0", "20", "query:alpha will", "type:artist"]` | Search artists, starting at offset 0 with at most 20 results. |
| `["phoneticsearch", "0", "20", "query:Alphaville"]`                | Search all four entity types.                                 |

Example:

```sh
curl -sS -H 'Content-Type: application/json' \
  --data '{"id":1,"method":"slim.request","params":["",["phoneticsearch","0","20","query:alpha will","type:artist"]]}' \
  'http://LMS_HOST:9000/jsonrpc.js'
```

The search syntax is `phoneticsearch <offset> <limit> query:<text> [type:<types>]`. `offset` is 0–1000, `limit` is 1–100, and `query` is required and at most 256 characters. `type` accepts `artist`, `album`, `track`, `genre`, or a comma-separated selection such as `artist,album`; omitting it searches all four. `mode:auto` is accepted but optional. Other mode values and `maxdistance` are rejected. The query is passed as one LMS command-array item, even when it contains spaces.

### Reading search results

The JSON-RPC envelope contains a `result` object. On success it has `index_state: "ready"`, `count` (number of hits in this page), `offset`, `limit`, `total_is_exact: 0`, and `results_loop` (the hit array). `count` is **not** a total across all pages. `total_is_exact: 0` means candidate retrieval is bounded; do not infer a complete library-wide hit count from pagination.

Each hit contains:

| Field            | Meaning                                                                                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `type`           | `artist`, `album`, `track` or `genre`.                                                                                                                                               |
| `id`             | The LMS database ID for that entity type. Use `type` together with `id`; the ID alone is not globally unique.                                                                        |
| `name`           | Current library name/title, checked against the source database.                                                                                                                     |
| `match_type`     | `exact`, `normalized`, `alias`, `prefix`, `partial`, `phonetic` or `partial_phonetic`. Partial matches apply to artists, albums and tracks; aliases apply to artists. The two phonetic types share a ranking class. |
| `score`          | A ranking value assigned by the plugin, **not** a probability or confidence percentage. Exact=1, normalized=0.95, alias=0.9, prefix=0.8, partial=0.75; phonetic classes use `0.7 / (1 + distance / 100)`. |
| `distance`       | Spellfix edit distance for phonetic matches; smaller is better. It is 0 for other match types.                                                                                       |
| `spellfix_score` | The underlying Spellfix score, used as a tie breaker within the same match class and distance.                                                                                       |

Hits are ordered first by match class, then distance, whole-title preference on a phonetic tie, Spellfix score, entity type and ID. Thus an exact `Pink` hit stays ahead of an alias suggestion for `P!nk`, and a complete exact track title stays ahead of a matching phrase within a longer title. A `phonetic` or `partial_phonetic` hit should be treated as a suggestion to the caller, especially before using it for an action. Partial matching uses whole words and adjacent phrases, not arbitrary character substrings.

### Reading status and errors

`phoneticsearch status ?` returns `state` plus available details: `error`, `last_success`, `last_mode`, `last_changes`, `last_verified`, `last_reconcile_duration_ms` and `worker_running`. The `last_*` timestamps are Unix seconds. `last_changes` counts changes from the last index operation; it is not the total index size. `worker_running` is 1 while the worker is alive and 0 otherwise.

Searches require `state: "ready"`. During a scan, `index_state` may be `updating` and the search returns `error: "index_not_ready"`. Other states include `stale`, `error`, `cleanup_pending`, `cleanup_complete` and `disabled`. Invalid search arguments return `invalid_parameter`; a missing index or binary can produce `index_not_ready` or `extension_unavailable`. An unexpected internal failure returns `internal_error`; inspect the LMS plugin log for its details. The JSON-RPC transport may still return HTTP 200 for these command-level errors.

## Settings and maintenance

The active plugin entry links to `settings/plugins/PhoneticSearch/settings/basic.html`. On that page you can inspect the status and last reconciliation duration, verify the index, or request a rebuild. Verification and rebuilding run asynchronously. If verification detects corruption or a source mismatch, the plugin rebuilds through a staging index.

The **Remove plugin data** action requires typing `DELETE`. It removes only the plugin cache and settings, then leaves the search disabled until the next LMS start. If the plugin remains installed, a restart recreates the index. An automatic pre-uninstall cleanup hook is not confirmed; follow the [test installation guide](docs/test-installation.md) when removing a test installation.

## Development checks

On Linux, run `python -m unittest discover -s poc -p 'test_*.py' -v`, `python -m poc.search_corpus`, `perl -Isrc/lib poc/test_scheduler_events.pl`, and `python scripts/package_test_plugin.py`. The CI workflow runs the platform builds and load checks and creates a fresh plugin ZIP on each push. Its expensive binary jobs use a cache key derived from the pinned SQLite/Spellfix source, build and loader code, platform matrix and load-test code. A failing platform does not cancel the other platform jobs; a push failure opens or updates a target-specific GitHub issue.

See [POC results](docs/poc-results.md), [compatibility](docs/compatibility.md) and [session progress](docs/progress.md) for actual observations and remaining limits.
