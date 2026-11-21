# Vorschläge für Lyrion Music Server aus dem PhoneticSearch-POC

Stand 2026-11-20. Diese Liste sammelt mögliche Verbesserungen **für eine spätere Diskussion mit dem LMS-Projekt**. Es wurden keine LMS-Core-Dateien geändert. Aktuell getestet wurde nur das isolierte LMS 9.2 auf Linux x86_64; für einen Upstream-Vorschlag sind weitere Messungen und eine Prüfung durch die Maintainer nötig.

## 1. Index auf `tracks.updated_time`

**Befund:** LMS 9.2 speichert `tracks.updated_time` und setzt den Wert bei Track-Erstellung und beim Metadaten-Update in `Slim/Schema.pm`. Die 1.205 Track-Zeilen der isolierten Testbibliothek hatten alle einen Wert. `PRAGMA index_list(tracks)` zeigte keinen Index auf dieser Spalte. `EXPLAIN QUERY PLAN SELECT id,title FROM tracks WHERE updated_time>=?` ergab `SCAN tracks`.

**POC-Messung:** Auf synthetischen SQLite-Tabellen mit einem neuen Track dauerte die nicht indizierte Abfrage bei 100.000 Zeilen median **6,477 ms** (p95 **7,209 ms**) und bei 500.000 Zeilen median **32,176 ms** (p95 **32,823 ms**), je 20 warme Läufe auf dem Debian-12-x86_64-Builder. Das ist noch kein LMS-Scannerbenchmark.

**Vorschlag zur Prüfung:** Ein Index wie `CREATE INDEX ... ON tracks(updated_time, id)` könnte Delta-Abfragen für Plugins und LMS-eigene Funktionen beschleunigen. Vor einer Empfehlung sind Speicherbedarf, Scan-/Update-Schreibkosten, Migration auf großen Bibliotheken und tatsächliche Query-Pläne im LMS zu messen. **PhoneticSearch legt diesen Index nicht eigenständig in `library.db` an.**

## 2. Änderungsinformation für Album, Contributor und Genre

**Befund:** Die tatsächlichen Tabellen `albums`, `contributors` und `genres` im LMS-9.2-Testbestand haben keine `updated_time`- oder vergleichbare Änderungsspalte. Ein ausschließlich zeitstempelbasierter Indexabgleich kann Änderungen an diesen drei Suchtypen daher nicht vollständig erfassen. Neue Einträge, die an einen neuen Track gebunden sind, lassen sich über dessen Beziehungen finden; direkte Umbenennungen und Löschungen bleiben ohne vollständigen Abgleich oder eine zusätzliche Änderungsquelle offen.

**Vorschlag zur Prüfung:** Einheitliche, bei allen relevanten Schreibpfaden gepflegte Änderungsmarker oder ein dokumentierter Änderungs-Event/Feed mit Typ, ID, Operation und Bibliotheksgeneration. Eine reine Zeitspalte löst Löschungen nicht; hierfür wäre ein Änderungsfeed oder Tombstone nötig. Semantik bei Scanner, Remote-Einträgen, Wipe und Migration müsste festgelegt werden.

## 3. Scan-Ende mit Ergebnis und Bibliotheksgeneration

**Befund:** `['rescan','done']` ist in den geprüften 9.1/9.2-Quellpfaden auch auf Abbruch-/Fehlerpfaden möglich. Ein erneuter echter 9.2-`wipecache` ließ die DB-Inode unverändert, die Track-Tabelle kurzzeitig auf 0 fallen und erzeugte mindestens 39 beobachtete Commit-Änderungen; Dateidentität allein zeigt diese neue Bibliotheksgeneration nicht an. Ein einzelner `rescan`-RPC auf dem isolierten LMS 9.2 lieferte beim Event-Probe zwei `rescan done`-Benachrichtigungen; ob sie unterschiedliche Scanphasen bezeichnen, ist noch nicht geklärt.

**Vorschlag zur Prüfung:** Ein dokumentiertes Scan-Ergebnis (`success`, `aborted`, `failed`) und ein monotoner Bibliotheksgenerations- oder Revisionsmarker würden Plugins helfen, nach einem Scan gezielt und sicher neu abzugleichen. Ein solcher Marker müsste In-place-Wipes, DB-Ersetzungen und Upgrades abdecken.

## 4. Verlässlicher Plugin-Cleanup vor Deinstallation

**Befund:** Im geprüften `Slim::Utils::PluginManager`-Pfad entfernt `_needsUninstall` das Plugin-Verzeichnis unter `InstalledPlugins`; ein aufgerufener Pre-Uninstall-Hook wurde dort nicht gefunden. Ein Plugin mit eigenen Cache-Dateien kann daher keinen automatischen Vorab-Cleanup voraussetzen.

**Vorschlag zur Prüfung:** Dokumentierter, fehlerbehandelter Lifecycle-Hook vor dem Entfernen der Plugin-Dateien oder ein klarer API-Vertrag für Plugin-Datenbereinigung. Bis dahin muss PhoneticSearch einen expliziten Admin-Cleanup vor Deinstallation anbieten und Restdaten dokumentieren.

## Priorisierung

Der fehlende `updated_time`-Index ist ein **Mess- und Diskussionskandidat**, noch kein nachgewiesener LMS-Engpass. Ein Änderungsfeed und ein eindeutiger Scan-/Generationsstatus wären für korrekte, kostengünstige Plugin-Indizes wertvoller, erfordern aber deutlich mehr LMS-Designarbeit. Alle Vorschläge bleiben getrennt von der aktuellen triggerfreien Plugin-Architektur.
