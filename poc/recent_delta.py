"""POC fast path from recently updated LMS tracks and their relationships.

This is deliberately incomplete: deletions and direct changes to other entity
tables still require a full reconciliation.
"""
from poc.lms_index_probe import apply_batch, text_name

MAX_FAST_TRACKS = 1000


def _batches(values, size=400):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def recent_entities(source, watermark):
    source.execute("BEGIN")
    try:
        # Inclusive comparison covers multiple writes in one timestamp second.
        rows = source.execute(
            "SELECT id,title,album,updated_time FROM tracks WHERE updated_time>=?",
            (watermark,)).fetchall()
        if len(rows) > MAX_FAST_TRACKS:
            source.commit()
            return None, len(rows), watermark
        found = {("track", ident): text_name(title) for ident, title, _, _ in rows if title}
        track_ids = [row[0] for row in rows]
        album_ids = sorted({row[2] for row in rows if row[2] is not None})
        newest = max((row[3] for row in rows if row[3] is not None), default=watermark)

        for ids in _batches(album_ids):
            marks = ",".join("?" for _ in ids)
            for ident, name in source.execute(f"SELECT id,title FROM albums WHERE id IN ({marks})", ids):
                if name:
                    found[("album", ident)] = text_name(name)
            for ident, name in source.execute(
                    "SELECT c.id,c.name FROM contributors c "
                    "JOIN contributor_album ca ON ca.contributor=c.id "
                    f"WHERE ca.album IN ({marks})", ids):
                if name:
                    found[("artist", ident)] = text_name(name)
        for ids in _batches(track_ids):
            marks = ",".join("?" for _ in ids)
            for ident, name in source.execute(
                    "SELECT c.id,c.name FROM contributors c "
                    "JOIN contributor_track ct ON ct.contributor=c.id "
                    f"WHERE ct.track IN ({marks})", ids):
                if name:
                    found[("artist", ident)] = text_name(name)
            for ident, name in source.execute(
                    "SELECT g.id,g.name FROM genres g "
                    "JOIN genre_track gt ON gt.genre=g.id "
                    f"WHERE gt.track IN ({marks})", ids):
                if name:
                    found[("genre", ident)] = text_name(name)
        source.commit()
        return found, len(rows), newest
    except BaseException:
        source.rollback()
        raise


def apply_recent(index, found):
    changed = []
    for (kind, ident), name in sorted(found.items()):
        row = index.execute(
            "SELECT original FROM ps_entity WHERE entity_type=? AND entity_id=?",
            (kind, ident)).fetchone()
        if not row or row[0] != name:
            changed.append((0, kind, ident, name))
    if changed:
        apply_batch(index, changed)
    return len(changed)
