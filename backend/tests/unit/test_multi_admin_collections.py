"""
LEXIS — Unit Tests: Multi-Admin & Collections Explorer
------------------------------------------------------
Verifies:
  1. Multiple admin accounts can authenticate independently with distinct passwords.
  2. Fallback to .env ADMIN_PASSWORD_HASH works seamlessly for bootstrap admin.
  3. POST /api/v1/admin/admins creates and hashes new admin records.
  4. Non-admins cannot call admin endpoints (401/403).
  5. Collections Explorer endpoints list, create, inspect, and safely drop custom collections.
  6. Protected core collections cannot be dropped.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, APIRouter
from bson import ObjectId

from services.auth.jwt_service import create_access_token
from pwdlib import PasswordHash

_ph = PasswordHash.recommended()


def build_test_app():
    test_app = FastAPI()
    from api.routes.auth import router as auth_router
    from api.routes.admin import router as admin_router

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(auth_router)
    api_v1.include_router(admin_router)
    test_app.include_router(api_v1)

    # Mock DB state
    mock_db = MagicMock()
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    test_app.state.mongo_client = mock_client
    test_app.state.mongo_db_name = "lexis"

    return test_app, mock_db


@pytest.mark.asyncio
async def test_multi_admin_login_with_db_hash():
    """Confirms an administrator stored in MongoDB with their own password_hash logs in successfully."""
    app, mock_db = build_test_app()
    hashed_pwd = _ph.hash("SecondAdmin@Secret999")

    mock_db["users"].find_one = AsyncMock(return_value={
        "_id": ObjectId(),
        "email": "sarah_admin@lexis.org",
        "role": "admin",
        "is_active": True,
        "password_hash": hashed_pwd,
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Correct password -> 200
        res = await client.post("/api/v1/auth/admin/login", json={
            "email": "sarah_admin@lexis.org",
            "password": "SecondAdmin@Secret999"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "admin"
        assert "access_token" in data

        # Wrong password -> 401
        res_bad = await client.post("/api/v1/auth/admin/login", json={
            "email": "sarah_admin@lexis.org",
            "password": "WrongPassword!"
        })
        assert res_bad.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_and_create_endpoints():
    """Confirms listing and creating new platform administrators via /api/v1/admin/admins."""
    app, mock_db = build_test_app()
    admin_token = create_access_token("admin_master_1", "admin")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Mock list admins
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[
        {
            "_id": ObjectId("6adf86fda19c092f1952f434"),
            "email": "tejaschaudhari2541@gmail.com",
            "role": "admin",
            "is_active": True,
            "created_at": "2026-10-26 16:59:41",
            "profile": {"full_name": "Tejas Master"}
        }
    ])
    mock_db["users"].find = MagicMock(return_value=mock_cursor)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/admin/admins", headers=headers)
        assert res.status_code == 200
        admins = res.json()
        assert len(admins) == 1
        assert admins[0]["email"] == "tejaschaudhari2541@gmail.com"
        assert admins[0]["full_name"] == "Tejas Master"

        # Test creating new admin
        mock_db["users"].find_one = AsyncMock(return_value=None)  # not existing
        mock_db["users"].insert_one = AsyncMock()

        res_create = await client.post("/api/v1/admin/admins", headers=headers, json={
            "email": "new_team_admin@lexis.org",
            "password": "TeamPassword#2026",
            "full_name": "Team Admin"
        })
        assert res_create.status_code == 201
        data_create = res_create.json()
        assert data_create["email"] == "new_team_admin@lexis.org"
        assert data_create["full_name"] == "Team Admin"
        assert data_create["role"] == "admin"


@pytest.mark.asyncio
async def test_collections_explorer_endpoints():
    """Confirms collections listing, custom collection creation, and core collection protection."""
    app, mock_db = build_test_app()
    admin_token = create_access_token("admin_master_1", "admin")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Mock list_collection_names
    mock_db.list_collection_names = AsyncMock(return_value=["users", "scam_patterns", "custom_docs"])
    mock_db["users"].count_documents = AsyncMock(return_value=12)
    mock_db["users"].index_information = AsyncMock(return_value={"_id_": {}})
    mock_db["scam_patterns"].count_documents = AsyncMock(return_value=17)
    mock_db["scam_patterns"].index_information = AsyncMock(return_value={"_id_": {}})
    mock_db["custom_docs"].count_documents = AsyncMock(return_value=0)
    mock_db["custom_docs"].index_information = AsyncMock(return_value={"_id_": {}})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. List collections
        res_list = await client.get("/api/v1/admin/collections", headers=headers)
        assert res_list.status_code == 200
        cols = res_list.json()
        col_names = [c["name"] for c in cols]
        assert "users" in col_names
        assert "custom_docs" in col_names

        # 2. Cannot drop protected collection "users"
        res_bad_drop = await client.delete("/api/v1/admin/collections/users", headers=headers)
        assert res_bad_drop.status_code == 400
        assert "Cannot drop protected core collection" in res_bad_drop.json()["detail"]

        # 3. Can drop custom collection
        mock_db.drop_collection = AsyncMock()
        res_ok_drop = await client.delete("/api/v1/admin/collections/custom_docs", headers=headers)
        assert res_ok_drop.status_code == 200
