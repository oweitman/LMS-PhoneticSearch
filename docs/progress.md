# Projektstatus für spätere Sitzungen

Stand: 2026-11-22. Infrastrukturadressen und lokale Pfade in den historischen POC-Notizen sind anonymisierte Platzhalter.

## Veröffentlichung und Repository

- Das ursprüngliche Repository mit privater Testhistorie wurde zu `oweitman/LMS-PhoneticSearch-private-archive` umbenannt und bleibt **PRIVATE**. Das neue `oweitman/LMS-PhoneticSearch` enthält nur den bereinigten Verlauf mit dem GitHub-Nutzernamen `oweitman` als Autor und ist seit 2026-11-22 **PUBLIC**.
- Alle eigentlichen Plugin-Dateien liegen in `src/`; Build-Skripte und POC-Tests liegen außerhalb. Das Installations-ZIP hat die von LMS verlangte Struktur mit `install.xml` unmittelbar im Archivstamm.
- [Release v0.1.11](https://github.com/oweitman/LMS-PhoneticSearch/releases/tag/v0.1.11) ist veröffentlicht und anonym erreichbar. `public.xml` liegt wie bei FadeTools im Hauptverzeichnis von `main` und ist der einzige künftig aktualisierte Katalog. Der Nutzer löscht den nicht mehr benötigten `plugin-feed`-Branch selbst.
- Das heruntergeladene Release-ZIP `PhoneticSearch-0.1.11.zip` bestand den ZIP-Integritätstest, enthält Icon und alle sechs Binärziele und trägt Version `0.1.11` sowie `minVersion=9.1.0`. SHA-1: `182ef04785e0895b98b9b6fe48278c7ac87eba84`; SHA-256: `3b36a910f3f2b7328a4f9be0aea6fdb9d95599340c719189558072e0aa3807a7`. Der anonym abgerufene Katalog trägt denselben SHA-1 und `minTarget=9.1.0`.
- [Actions-Lauf 44967206198](https://github.com/oweitman/LMS-PhoneticSearch/actions/runs/44967206198) scheiterte nach der 9.1-Umstellung nur an einer fest auf 9.2.0 gesetzten Prüfung im lokalen POC-Paketskript. [Lauf 44967607062](https://github.com/oweitman/LMS-PhoneticSearch/actions/runs/44967607062) bestand nach der Korrektur Unit-, sechs Binary-, Paket- und Feed-Job und veröffentlichte v0.1.11. Eine zusätzliche Prüfung vergleicht nun `public.xml` und `feed-state.json` auch bei `minTarget`.
- Ein reiner Dokumentationslauf vor der Identitätskorrektur nutzte auf allen sechs Zielen geprüfte Cache-Treffer; die Kompilierungs- und Ladetest-Schritte waren übersprungen. Das Release blieb `v0.1.1`, der Feed unverändert.
- Nach Korrektur der Commit-Identität ordnet GitHub Haupt- und Feed-Commit dem Konto `oweitman` zu. [Actions-Lauf 44961066998](https://github.com/oweitman/LMS-PhoneticSearch/actions/runs/44961066998) auf dem neuen Hauptbranch bestand alle Unit-, sechs Binary-, Paket- und Feed-Jobs. Release-Tag, Release-Metadaten und Feed zeigen auf den korrigierten Verlauf; das geprüfte Release-ZIP blieb bytegleich. Der Workflow reagiert künftig nur auf Pushes nach `main`, Pull Requests und manuelle Starts.
- [Actions-Lauf 44962300695](https://github.com/oweitman/LMS-PhoneticSearch/actions/runs/44962300695) bestand nach der Verlagerung von `public.xml` auf `main` ebenfalls vollständig. Anonyme HTTP-Prüfung nach Sichtbarkeitswechsel: `main/public.xml`, `plugin-feed/public.xml`, Icon und Release-ZIP antworteten jeweils mit 200. Ein echter LMS-Plugin-Manager-Installationslauf steht weiterhin aus.
- Historische POC-Messungen und Fehler stehen in [poc-results.md](poc-results.md); Plattformgrenzen in [compatibility.md](compatibility.md). Alte Actions-IDs dort gehören zum privaten Archiv und sind öffentlich nicht abrufbar.

## Bewiesener Funktionsumfang

- Das komplette Plugin lief auf isoliertem LMS **9.2.0/Linux x86_64**: Einstellungen, Worker, Index, Status- und Such-API, `alpha will` und `alfa will` → `Alphaville`, Rescan-/Fehlerfälle und Cleanup. Ein zweiter isolierter Testserver lud das manuell installierte Plugin; API, Icon und Einstellungslink antworteten. Diese Live-Tests betrafen frühere ZIP-Stände, nicht den Release-Download über den Plugin-Manager.
- Die aktuelle Actions-Matrix baute und lud die SQLite-Erweiterung auf Linux x86_64/aarch64/armv7, macOS x86_64/arm64 und Windows x86_64. Der Linux-x86_64-Job lud sie zusätzlich mit der gepinnten LMS-9.2-Perl-Runtime. Für die anderen fünf Ziele ist kein vollständiger LMS-Plugin-Lauf bewiesen.
- Der Quellindex ist eine getrennte SQLite-Datei ohne Trigger in `library.db`. Der Poll startet standardmäßig nach fünf Sekunden und ist auf der Plugin-Seite konfigurierbar; der nächste Tick wird erst nach Abschluss des vorherigen Workers geplant. Nach Scan-Ende oder spätestens 900 Sekunden wird vollständig abgeglichen. Synthetische Lasttests bis 500.000 Tracks stehen in [poc-results.md](poc-results.md).
- `src/install.xml` und der aktuelle Katalog deklarieren LMS 9.1.0 als Mindestversion. Das ältere Release v0.1.1 verlangt weiterhin 9.2.0. Der vollständige Plugin-Lauf auf LMS 9.1 ist noch nicht getestet. Eine produktive Installation wurde nicht ausgeführt.

## Reproduzierbare Befehle

```sh
python -m unittest discover -s poc -p 'test_*.py' -v
python -m poc.search_corpus
perl -Isrc/lib poc/test_interval.pl
perl -Isrc/lib poc/test_loader_platforms.pl
python scripts/package_test_plugin.py
python scripts/ci_binary.py matrix
```

Der vollständige Binary- und Feed-Lauf steht in `.github/workflows/poc.yml`. `python scripts/package_test_plugin.py` erzeugt ein lokales Linux-x86_64-Testpaket; `scripts/prepare_feed.py` akzeptiert für Veröffentlichungen nur ein vollständiges Sechs-Ziel-Paket. Historische Live-Testbefehle stehen in [poc-results.md](poc-results.md). Niemals eine produktive LMS-Datenbank für diese POC-Skripte verwenden.

## Nächste Schritte

1. Die Feed-URL aus [README.md](../README.md) in einem separaten LMS 9.2 unter **Settings > Plugins > Additional repositories** eintragen. Plugin-Manager-Installation, Neustart, Einstellungen, `phoneticsearch status ?` und `alpha will` prüfen. Testserver und Testbibliothek verwenden.
2. Für Linux x86_64 einen längeren Lauf mit einer größeren echten Bibliothek messen. Für weitere Plattformen vollständige LMS-Laufzeittests und die Windows-Zufallsquelle für den Formular-Token ergänzen. LMS 9.1 später separat prüfen.
3. Den fehlenden verlässlichen Pre-Uninstall-Hook als Upstream-Thema verfolgen; bis dahin die getestete Cleanup-Aktion auf der Plugin-Seite verwenden. Weitere Vorschläge stehen in [lms-upstream-proposals.md](lms-upstream-proposals.md).
