import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self._rows = []

    def execute(self, sql, params=()):
        self.connection.executed_sql.append(sql)
        self.connection.executed_params.append(params)
        if sql.lstrip().upper().startswith("SELECT") and self.connection.results:
            columns, rows = self.connection.results.pop(0)
            self.description = [(name,) for name in columns]
            self._rows = rows
        return self

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    """In-memory DB-API double for unit tests; never used outside tests."""

    def __init__(self):
        self.executed_sql = []
        self.executed_params = []
        self.results = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def fake_connection():
    return FakeConnection()
