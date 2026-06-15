"""
Test script - confirms Python can connect to the local PostgreSQL database.

Run from the backend/ folder:
    python scripts/test_db_connection.py
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def main():
    if not DATABASE_URL:
        print("FAILED: DATABASE_URL is not set in backend/.env")
        sys.exit(1)

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT NOW();")
        current_time = cur.fetchone()[0]
        cur.close()
        conn.close()
    except Exception as e:
        print(f"FAILED to connect to the database: {e}")
        sys.exit(1)

    print("SUCCESS: Connected to PostgreSQL")
    print(f"Database server time: {current_time}")


if __name__ == "__main__":
    main()
