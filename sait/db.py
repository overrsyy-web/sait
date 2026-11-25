"""Минимальная обёртка над pyodbc для работы с Microsoft Access."""
import os
import pyodbc
from datetime import datetime

class Db:
    def __init__(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"❌ Файл базы данных не найден: {path}")
        self._conn = pyodbc.connect(
            r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
            f"DBQ={path};"
        )
        self._conn.autocommit = False

    def _cursor(self):
        return self._conn.cursor()

    def query(self, sql, params=()):
        cur = self._cursor()
        if params:
            cur.execute(sql, tuple(params))
        else:
            cur.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        cur = self._cursor()
        if params:
            cur.execute(sql, tuple(params))
        else:
            cur.execute(sql)
        return cur.rowcount

    def insert(self, sql, params=()):
        cur = self._cursor()
        if params:
            cur.execute(sql, tuple(params))
        else:
            cur.execute(sql)
        cur.execute("SELECT @@IDENTITY")
        return int(cur.fetchone()[0])

    def commit(self):
        try: self._conn.commit()
        except Exception: pass

    def rollback(self):
        try: self._conn.rollback()
        except Exception: pass

    def close(self):
        try: self._conn.close()
        except Exception: pass

    @staticmethod
    def now():
        return datetime.now()