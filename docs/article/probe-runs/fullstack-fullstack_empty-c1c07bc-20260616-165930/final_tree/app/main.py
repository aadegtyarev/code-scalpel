from contextlib import asynccontextmanager

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
from fastapi import FastAPI
from sqlalchemy import create_engine

from app.config import settings
from app.routes import router


def _run_alembic_upgrade() -> None:
    """Run alembic migrations synchronously at startup.

    Uses a sync engine because Alembic's async runner requires
    an event loop that might not match the FastAPI lifespan loop.
    Fallback to a sync connection for the migration step.
    """
    # Build a sync URL from the async one
    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    sync_url = sync_url.replace("asyncpg", "psycopg2")

    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    script = ScriptDirectory.from_config(alembic_cfg)

    def upgrade_to_head(rev, context):
        return script._upgrade_revs("head", rev)

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        with EnvironmentContext(alembic_cfg, script, fn=upgrade_to_head):
            alembic_cfg.attributes["connection"] = connection
            script.run_env()
    engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: run migrations
    _run_alembic_upgrade()
    yield
    # Shutdown: nothing to clean up


app = FastAPI(title="API Key Management", lifespan=lifespan)
app.include_router(router)
