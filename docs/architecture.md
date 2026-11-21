# Architektur von PhoneticSearch

Stand 2026-11-21. Nur das isolierte LMS 9.2.0 auf Linux x86_64 ist für diese integrierte Implementierung geprüft. LMS 9.1 bleibt die geplante Mindestversion für die spätere Matrix.

## Daten und Aktualisierung

1. Das Plugin hält im LMS-Prozess eine read-only-Verbindung zu `library.db` und prüft `PRAGMA data_version` sowie die Dateiidentität. Der Poll-Takt ist standardmäßig 5 Sekunden und in den Einstellungen zwischen 5 und 3600 Sekunden wählbar. Es läuft maximal ein Worker; der nächste automatische Tick wird erst ab Abschluss des vorherigen Workers um das konfigurierte Intervall verzögert. Unveränderte Ticks lesen keine Namen und starten keinen Worker. Die Dauer des letzten automatischen Abgleichs wird angezeigt; oberhalb des Intervalls erscheint eine Empfehlung mit 25 % Reserve (bis zur Obergrenze 3600 s).
2. Bei Änderung liest ein separater Perl-Worker `tracks.updated_time` und die zugehörigen Alben, Contributors und Genres. Er schreibt ausschließlich `cache/PhoneticSearch/index.db`. Bis zu 5000 jüngste Tracks pro Lauf nutzen diesen Pfad; darüber wird neu aufgebaut. Auf einer synthetischen 100k-Kopie brauchten 1000 umbenannte Tracks 530 ms Worker-Zeit.
3. Nach Scan-Ende und spätestens nach 900 Sekunden vergleicht ein differenzieller Vollabgleich alle vier Entitätstabellen. Initialaufbau, Quelldateiersatz, Schemawechsel und expliziter Neuaufbau verwenden Staging-Datei und atomaren Tausch. Eine Dateisperre serialisiert Writer und bereinigt verwaiste Staging-Dateien.
4. Während LMS scannt, pausiert der Worker und die API meldet `updating`/`index_not_ready`. Scan-Ende-Signale werden über fünf Sekunden Ruhezeit zusammengefasst. Quellenänderungen während eines Snapshots führen zu `stale` und zeitnahem Wiederanlauf; echte Worker-Fehler zu einem 60-Sekunden-Retry-Abstand.
5. Indexschema **3** enthält vier Spellfix-Tabellen, einen B-Tree für exakte Namen, normalisierte Präfixe und eine Artist-Aliastabelle. `!` wird in Aliasen als `i` interpretiert. Dadurch bleibt `Pink` exakt vorn und `P!nk` erscheint als Aliasvorschlag. Für Artist-Suche kommen außerdem die generischen Query-Varianten `the <Wort>` und `dsch`→`j` zum Einsatz. Alle Treffer werden gegen aktuelle LMS-Namen validiert.

`score` ist ein Sortierwert, keine Wahrscheinlichkeit; `total_is_exact=0` kennzeichnet begrenzte Kandidaten. Die lesende API bietet `phoneticsearch status ?` und `phoneticsearch <offset> <limit> query:<Text> [type:artist,album,track,genre]`. Es gibt keine Plugin-Trigger, Queue oder LMS-Core-Änderungen in `library.db`. `Bin/manifest.json` bindet das Linux-x86_64-Binary an SHA-256; SQLite-Extension-Loading wird nur kurz zum Laden aktiviert.

## Wartung auf der Plugin-Seite

Die Settings-Seite bietet **Index prüfen**, **Index neu aufbauen** und **Plugin-Daten vollständig entfernen**. Ein 32-Byte-Zufallstoken aus `/dev/urandom` schützt die schreibenden Formularaktionen gegen blinde Fremd-POSTs; das LMS selbst muss für den gewünschten Zugriff auf seine Einstellungsseiten konfiguriert werden. Cleanup verlangt zusätzlich die Eingabe `DELETE`. Prüfung und Neuaufbau laufen asynchron im bestehenden Worker. Die Prüfung vergleicht Quell- und Indexentitäten, Vocabulary, Aliase, Spellfix-Zahlen und SQLite-Integrität; ein nachgewiesener Unterschied löst einen Staging-Neuaufbau aus.

Cleanup wartet auf laufenden Scan und Worker, stoppt Timer/Abo/Handles, entfernt nur den Plugin-Cache und die Plugin-Einstellungsdatei und setzt den Status `cleanup_complete`. Die Suche bleibt bis zum nächsten LMS-Start deaktiviert. Bei installiert bleibendem Plugin baut ein Neustart den Index neu auf; für die Deinstallation kann der Nutzer nach Cleanup den Server stoppen und das Plugin entfernen. Auf dem isolierten LMS blieben Cache und Prefs nach dem Stopp tatsächlich entfernt. Ein verlässlicher Pre-Uninstall-Hook des Plugin-Managers ist weiterhin nicht nachgewiesen. `scripts/cleanup_plugin_data.py` bleibt als Fallback für den gestoppten Server.

## Grenzen

- Der 5-Sekunden-Wert ist ein Poll-Takt, keine garantierte End-to-End-Latenz. Direkte Änderungen an Tabellen ohne Änderungszeit und Löschungen außerhalb eines Scans können bis zum 900-Sekunden-Abgleich warten. `tracks.updated_time` besitzt im geprüften 9.2-Schema keinen Index.
- Auf einer synthetischen 100k-Kopie lagen warme p95-Suchen unter 250 ms. Bei 500k ähnlich benannten Tracks waren es nach Optimierung 477/667 ms. Der Nutzer akzeptierte die gemessenen Zeiten. Ein großer realer Musikbestand stand nicht zur Verfügung.
- Das integrierte Korpus erreichte 5/5 Tippfehler und 3/3 ASR als Top 1. „Pink“ bleibt exakt auf Platz 1; „P!nk“ erscheint unter den Top-5-Vorschlägen. Die kleine Stichprobe ist keine allgemeine ASR-Garantie.
- LMS 9.1, vollständige LMS-Laufzeittests auf weiteren Plattformen, automatisches Plugin-Manager-Cleanup und ein produktiver Langzeittest sind offen. Die CI-Matrix prüft das Laden der Binaries auf sechs Zielen; das ist kein vollständiger Plugin-Laufzeittest.
