import pytest

from app.db import session


@pytest.fixture(autouse=True)
def audit_db(tmp_path):
    session.configure("sqlite:///" + str(tmp_path / "audit.db").replace("\\", "/"))
    yield
    session.reset()