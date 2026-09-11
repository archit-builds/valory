import mongomock
import pytest

from app.db import ensure_indexes


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["valory_test"]
    ensure_indexes(database)
    return database
