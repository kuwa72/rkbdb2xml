#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dump all tables from the Rekordbox 6 database into CSV files under a temp directory.
Usage:
  python dump_db_tables.py [path_to_database] [output_dir]
If path_to_database is omitted, auto-detection is used. Default output_dir is 'temp'.
"""
import sys
import csv
from pathlib import Path
import sqlalchemy
from pyrekordbox.db6 import Rekordbox6Database

def export_tables(db_path=None, out_dir='temp'):
    # Connect to Rekordbox 6 database (auto-detect if no path)
    if db_path:
        db = Rekordbox6Database(db_path)
    else:
        db = Rekordbox6Database()
    engine = db.engine
    # Prepare output directory
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    # Inspect table names
    inspector = sqlalchemy.inspect(engine)
    tables = inspector.get_table_names()
    # Export each table
    with engine.connect() as conn:
        for table in tables:
            try:
                print(f"Exporting table '{table}' to CSV...")
            except UnicodeEncodeError:
                pass
            stmt = sqlalchemy.text(f'SELECT * FROM "{table}"')
            result = conn.execute(stmt)
            columns = result.keys()
            csv_file = out_path / f"{table}.csv"
            with csv_file.open('w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                for row in result:
                    writer.writerow(row)
    try:
        print(f"Exported {len(tables)} tables to '{out_path}'")
    except UnicodeEncodeError:
        pass

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) >= 2 else None
    out_dir = sys.argv[2] if len(sys.argv) >= 3 else 'temp'
    export_tables(db_path, out_dir)
