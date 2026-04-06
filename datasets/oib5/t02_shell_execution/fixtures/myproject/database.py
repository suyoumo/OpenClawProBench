import sqlite3
from config import DATABASE_URL

def get_connection():
    return sqlite3.connect(DATABASE_URL)

def execute_query(query, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params or ())
    conn.commit()
    return cursor.fetchall()

def close_connection(conn):
    conn.close()
