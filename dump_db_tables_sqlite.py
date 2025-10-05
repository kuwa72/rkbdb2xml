#!/usr/bin/env python3
"""
Dump all tables from a Rekordbox 6 SQLite database into CSV files under a temp directory.
Usage:
  python dump_db_tables_sqlite.py [path_to_db] [output_dir]
If path_to_db is omitted, auto-detects in %APPDATA%/Pioneer/rekordbox.
"""
import sys
import sqlite3
import csv
from pathlib import Path

def find_default_db():
    home = Path.home()
    default_dir = home / 'AppData' / 'Roaming' / 'Pioneer' / 'rekordbox'
    if default_dir.is_dir():
        dbs = list(default_dir.glob('*.db'))
        if dbs:
            # pick the first one
            return str(dbs[0])
    return None

def export_tables(db_file, out_dir='temp'):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cursor.fetchall()]
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    for table in tables:
        try:
            cursor.execute(f"SELECT * FROM '{table}';")
            cols = [d[0] for d in cursor.description]
            csv_file = out_path / f"{table}.csv"
            with csv_file.open('w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(cols)
                for row in cursor.fetchall():
                    writer.writerow(row)
        except Exception:
            continue
    print(f"Exported {len(tables)} tables from {db_file} to '{out_path}'")

if __name__ == '__main__':
    db_file = sys.argv[1] if len(sys.argv) > 1 else None
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'temp'
    if not db_file:
        db_file = find_default_db()
        if not db_file:
            print("Usage: python dump_db_tables_sqlite.py [path_to_db] [output_dir]")
            sys.exit(1)
    export_tables(db_file, out_dir)
