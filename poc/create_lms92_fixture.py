"""Create a disposable LMS-9.2-column fixture for Perl runtime CI tests."""
import argparse
import sqlite3
from pathlib import Path


def create(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE tracks(id INTEGER PRIMARY KEY, url TEXT UNIQUE,
                title TEXT, audio INTEGER, remote INTEGER, album INTEGER,
                updated_time INTEGER);
            CREATE TABLE albums(id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE contributors(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE genres(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE contributor_album(album INTEGER, contributor INTEGER);
            CREATE TABLE contributor_track(role INTEGER, contributor INTEGER,
                track INTEGER);
            CREATE TABLE genre_track(genre INTEGER, track INTEGER);
        ''')
        db.executemany('INSERT INTO albums(id,title) VALUES (?,?)',
                       ((i, f'Album {i}') for i in range(1, 98)))
        db.executemany('INSERT INTO contributors(id,name) VALUES (?,?)',
                       ((i, 'Alphaville' if i == 1 else
                         'Pink' if i == 2 else f'Artist {i}')
                        for i in range(1, 175)))
        db.executemany('INSERT INTO genres(id,name) VALUES (?,?)',
                       ((i, f'Genre {i}') for i in range(1, 24)))
        db.executemany(
            'INSERT INTO tracks(id,url,title,audio,remote,album,updated_time) '
            'VALUES (?,?,?,1,0,?,?)',
            ((i, f'file:///fixture-{i}', f'Track {i}', (i % 97) + 1,
              1000000 + i) for i in range(1, 1206)))
        db.execute('INSERT INTO contributor_album VALUES (1,1)')
        db.execute('INSERT INTO contributor_track VALUES (1,1,1)')
        db.execute('INSERT INTO genre_track VALUES (1,1)')
    print(f'fixture={path} tracks=1205 albums=97 artists=174 genres=23')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    args = parser.parse_args()
    create(args.path)


if __name__ == '__main__':
    main()
