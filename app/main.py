from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqladmin import Admin
from starlette.middleware.sessions import SessionMiddleware

from app.admin.auth_backend import AdminAuth
from app.admin.views import ALL_VIEWS
from app.api.v1 import auth, favorites, profiles, scans, search, sync
from app.core.config import get_settings
from app.core.db import admin_engine

settings = get_settings()

app = FastAPI(title="FoodLence API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only used by the SQLAdmin login session cookie — unrelated to the JWT
# auth flow used by everything under /api/v1.
app.add_middleware(SessionMiddleware, secret_key=settings.admin_session_secret)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(profiles.router, prefix="/api/v1")
app.include_router(scans.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(favorites.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")

admin = Admin(app, engine=admin_engine, authentication_backend=AdminAuth(secret_key=settings.admin_session_secret), base_url="/admin")
for view in ALL_VIEWS:
    admin.add_view(view)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}
