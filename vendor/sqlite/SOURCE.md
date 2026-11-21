# SQLite POC sources

All three files target SQLite **3.45.1**. `spellfix.c` and `sqlite3ext.h` were copied byte-for-byte from [SQLite Git commit `189e44dfecdc7868bb860dfb5d98eab371318c37`](https://github.com/sqlite/sqlite/tree/189e44dfecdc7868bb860dfb5d98eab371318c37), tag `version-3.45.1`. `sqlite3.h` was extracted from the [official 3.45.1 amalgamation ZIP](https://www.sqlite.org/2024/sqlite-amalgamation-3450100.zip). No SQLite library is linked into the extension; the header is for compilation only.

| File | SHA-256 |
|---|---|
| `spellfix.c` | `5a798cf5b5971252ad355622f0987c88e700519f0444ed6f9d678de633bf944a` |
| `sqlite3ext.h` | `b184dd1586d935133d37ad76fa353faf0a1021ff2fdedeedcc3498fff74bbb94` |
| `sqlite3.h` | `41e066ccd4f89e938f136ceb48c996c54dc381b59fe566dea48864c3750b779e` |
| source ZIP | `5592243caf28b2cdef41e6ab58d25d653dfc53deded8450eb66072c929f030c4` |

SQLite source code is dedicated to the public domain. [SQLite extension compilation and loading documentation](https://www.sqlite.org/loadext.html).
