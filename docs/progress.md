# Projektstatus für spätere Sitzungen

Stand: 2026-11-22. Infrastrukturadressen und lokale Pfade in den historischen POC-Notizen sind anonymisierte Platzhalter.

## Veröffentlichung und Repository

- Das ursprüngliche Repository mit privater Testhistorie wurde zu `oweitman/LMS-PhoneticSearch-private-archive` umbenannt und bleibt **PRIVATE**. Das neue `oweitman/LMS-PhoneticSearch` enthält nur einen bereinigten Root-Commit mit dem GitHub-Nutzernamen `oweitman` als Autor und bleibt bis zur Sichtbarkeitsänderung durch den Eigentümer **PRIVATE**.
- Alle eigentlichen Plugin-Dateien liegen in `src/`; Build-Skripte und POC-Tests liegen außerhalb. Das Installations-ZIP hat die von LMS verlangte Struktur mit `install.xml` unmittelbar im Archivstamm.
- Der historische erste Actions-Lauf 44930401220 bestand Unit-, sechs unabhängige Binary-, Paket- und Feed-Jobs. [Release v0.1.1](https://github.com/oweitman/LMS-PhoneticSearch/releases/tag/v0.1.1) ist veröffentlicht, aber wegen der privaten Repository-Sichtbarkeit noch nicht anonym erreichbar.
- Das authentifiziert heruntergeladene Release-ZIP `PhoneticSearch-0.1.1.zip` bestand den ZIP-Integritätstest, enthält Icon und alle sechs Binärziele und trägt Version `0.1.1`. SHA-1: `2436fc560746bf492d85545248e139bcd4329f83`; SHA-256: `90d0097ff00994836745f2c3b1cb967289f35a94ba16941b0fedb8cb0b6a51e3`. `plugin-feed/public.xml` enthält denselben SHA-1 und die Release-URL.
- Der historische reine Dokumentationslauf 44930958259 bestand. Alle sechs Binärjobs nutzten geprüfte Cache-Treffer; sämtliche Kompilierungs- und Ladetest-Schritte waren übersprungen. Das Release blieb `v0.1.1`, der Feed unverändert.
- Historische POC-Messungen und Fehler stehen in [poc-results.md](poc-results.md); Plattformgrenzen in [compatibility.md](compatibility.md). Alte Actions-IDs dort gehören zum privaten Archiv und sind öffentlich nicht abrufbar.

## Bewiesener Funktionsumfang

- Das komplette Plugin lief auf isoliertem LMS **9.2.0/Linux x86_64**: Einstellungen, Worker, Index, Status- und Such-API, `alpha will` und `alfa will` → `Alphaville`, Rescan-/Fehlerfälle und Cleanup. Ein zweiter isolierter Testserver lud das manuell installierte Plugin; API, Icon und Einstellungslink antworteten. Diese Live-Tests betrafen frühere ZIP-Stände, nicht den Release-Download über den Plugin-Manager.
- Die aktuelle Actions-Matrix baute und lud die SQLite-Erweiterung auf Linux x86_64/aarch64/armv7, macOS x86_64/arm64 und Windows x86_64. Der Linux-x86_64-Job lud sie zusätzlich mit der gepinnten LMS-9.2-Perl-Runtime. Für die anderen fünf Ziele ist kein vollständiger LMS-Plugin-Lauf bewiesen.
- Der Quellindex ist eine getrennte SQLite-Datei ohne Trigger in `library.db`. Der Poll startet standardmäßig nach fünf Sekunden und ist auf der Plugin-Seite konfigurierbar; der nächste Tick wird erst nach Abschluss des vorherigen Workers geplant. Nach Scan-Ende oder spätestens 900 Sekunden wird vollständig abgeglichen. Synthetische Lasttests bis 500.000 Tracks stehen in [poc-results.md](poc-results.md).
- `install.xml` verlangt derzeit LMS 9.2.0. LMS 9.1 ist das längerfristige Kompatibilitätsziel, aber für das integrierte Plugin noch nicht freigegeben. Eine produktive Installation wurde nicht ausgeführt.

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

1. Der Eigentümer stellt **nur das neue bereinigte Repository** auf PUBLIC. Dann Feed-URL und Release-URL ohne Anmeldung abrufen und SHA-1 erneut vergleichen.
2. Die Feed-URL aus [README.md](../README.md) in einem separaten LMS 9.2 unter **Settings > Plugins > Additional repositories** eintragen. Plugin-Manager-Installation, Neustart, Einstellungen, `phoneticsearch status ?` und `alpha will` prüfen. Testserver und Testbibliothek verwenden.
3. Für Linux x86_64 einen längeren Lauf mit einer größeren echten Bibliothek messen. Für weitere Plattformen vollständige LMS-Laufzeittests und die Windows-Zufallsquelle für den Formular-Token ergänzen. LMS 9.1 später separat prüfen.
4. Den fehlenden verlässlichen Pre-Uninstall-Hook als Upstream-Thema verfolgen; bis dahin die getestete Cleanup-Aktion auf der Plugin-Seite verwenden. Weitere Vorschläge stehen in [lms-upstream-proposals.md](lms-upstream-proposals.md).
