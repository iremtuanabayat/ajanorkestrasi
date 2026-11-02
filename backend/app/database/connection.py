from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_tables():
    from app.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # Small additive migration for existing local SQLite installations.
    if settings.database_url.startswith("sqlite"):
        columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
        migrations = {
            "project_id": "VARCHAR(36)",
            "task_type": "VARCHAR(40) NOT NULL DEFAULT 'information'",
            "current_step": "VARCHAR(40) NOT NULL DEFAULT 'pending'",
            "selected_agents": "JSON NOT NULL DEFAULT '[]'",
            "execution_logs": "JSON NOT NULL DEFAULT '[]'",
            "generated_files": "JSON NOT NULL DEFAULT '[]'",
            "preview_url": "VARCHAR(500)",
            "test_results": "JSON",
        }
        with engine.begin() as connection:
            for column, definition in migrations.items():
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE tasks ADD COLUMN {column} {definition}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
