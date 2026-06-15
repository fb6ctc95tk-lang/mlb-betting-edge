"""
Database connection helper for the FastAPI backend.

Loads DATABASE_URL from backend/.env and opens a new psycopg2
connection on request. No connection pooling, no SQLAlchemy -
each endpoint opens a connection, uses it, and closes it.
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)
