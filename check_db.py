from sqlalchemy import inspect, text

from app.db.session import configure, get_engine

configure()
engine = get_engine()
with engine.connect() as conn:
    print("dialect:", engine.dialect.name, "| select 1 ->", conn.execute(text("SELECT 1")).scalar())
print("tables:", sorted(inspect(engine).get_table_names()))