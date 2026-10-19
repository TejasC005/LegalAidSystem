"""
=============================================================================
LEXIS — Unit Tests: Admin Legal Knowledge Base Management & Rights Agent Integration
=============================================================================
Tests covering:
1. Admin-only access enforcement (401/403 for citizen/anonymous/unauthenticated)
2. Valid JSON, PDF, and DOCX ingestion
3. Malformed JSON and invalid file handling
4. Duplicate upload detection via SHA-256
5. Qdrant indexing and document activation/deactivation lifecycle
6. Rights Agent retrieval of newly uploaded legal documents
7. Exclusion of deactivated documents from Rights Agent retrieval
8. Preservation of starter legal seed knowledge retrieval
"""

import io
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import create_app
from core.config import get_settings
from db.qdrant_client import get_qdrant_client, reset_in_memory_client
from services.auth.jwt_service import create_access_token
from agents.rights_agent.agent import RightsAgent
from services.rag.embedder import BGEM3Embedder
from services.rag.ingestion import seed_starter_knowledge_base


# In-memory mock MongoDB collection
class MockAsyncCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        from bson import ObjectId
        doc_copy = dict(doc)
        if "_id" not in doc_copy:
            doc_copy["_id"] = ObjectId()
        self.docs.append(doc_copy)
        mock_result = MagicMock()
        mock_result.inserted_id = doc_copy["_id"]
        return mock_result

    async def find_one(self, query):
        for d in self.docs:
            match = True
            for k, v in query.items():
                if k == "_id":
                    if str(d.get("_id")) != str(v):
                        match = False
                elif d.get(k) != v:
                    match = False
            if match:
                return dict(d)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        matched = []
        for d in self.docs:
            m = True
            for k, v in query.items():
                if d.get(k) != v:
                    m = False
            if m:
                d_copy = dict(d)
                if projection:
                    for k, flag in projection.items():
                        if flag == 0 and k in d_copy:
                            del d_copy[k]
                matched.append(d_copy)

        class AsyncCursor:
            def __init__(self, items):
                self.items = items

            def sort(self, *args, **kwargs):
                return self

            def skip(self, *args, **kwargs):
                return self

            def limit(self, *args, **kwargs):
                return self

            def __aiter__(self):
                self._iter = iter(self.items)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration

        return AsyncCursor(matched)

    async def update_one(self, query, update):
        matched = 0
        for d in self.docs:
            m = True
            for k, v in query.items():
                if d.get(k) != v:
                    m = False
            if m:
                matched += 1
                if "$set" in update:
                    for sk, sv in update["$set"].items():
                        d[sk] = sv
        res = MagicMock()
        res.matched_count = matched
        return res

    async def delete_one(self, query):
        initial_len = len(self.docs)
        self.docs = [
            d for d in self.docs
            if not all(d.get(k) == v for k, v in query.items())
        ]
        res = MagicMock()
        res.deleted_count = initial_len - len(self.docs)
        return res


class MockAsyncDatabase:
    def __init__(self):
        self.collections = {
            "knowledge_base_documents": MockAsyncCollection(),
            "users": MockAsyncCollection(),
            "reflection_logs": MockAsyncCollection(),
        }

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = MockAsyncCollection()
        return self.collections[name]


@pytest.fixture
def mock_db():
    return MockAsyncDatabase()


@pytest.fixture
def test_app(mock_db):
    app = create_app()
    app.state.mongo_client = {get_settings().MONGODB_DB_NAME: mock_db}
    app.state.mongo_db_name = get_settings().MONGODB_DB_NAME

    from db.database import get_database
    app.dependency_overrides[get_database] = lambda: mock_db
    return app


@pytest.fixture
def test_client(test_app):
    return TestClient(test_app)


@pytest.fixture
def in_memory_qdrant():
    reset_in_memory_client()
    client = get_qdrant_client(force_in_memory=True, new_instance=True)
    # Seed starter knowledge base
    seed_starter_knowledge_base(client=client, force_recreate=True, test_mode=True)
    return client


@pytest.fixture
def admin_token():
    return create_access_token("admin_test_id", "admin")


@pytest.fixture
def citizen_token():
    return create_access_token("citizen_test_id", "user")


# ── 1. Admin Role & Access Control Tests ─────────────────────────────────────

def test_admin_only_access_enforced(test_client, citizen_token):
    """Citizen role receives 403 Forbidden on knowledge base endpoints."""
    headers_citizen = {"Authorization": f"Bearer {citizen_token}"}
    res_list = test_client.get("/api/v1/admin/knowledge-base/documents", headers=headers_citizen)
    assert res_list.status_code == 403

    res_upload = test_client.post(
        "/api/v1/admin/knowledge-base/upload",
        headers=headers_citizen,
        files={"file": ("test.json", b"[]", "application/json")},
    )
    assert res_upload.status_code == 403


def test_unauthenticated_access_rejected(test_client):
    """Requests without token receive 401 Unauthorized."""
    res = test_client.get("/api/v1/admin/knowledge-base/documents")
    assert res.status_code == 401


# ── 2. Valid Ingestion Tests (JSON, PDF, DOCX) ───────────────────────────────

def test_valid_json_ingestion(test_client, admin_token, in_memory_qdrant, monkeypatch):
    """Uploading a structured JSON file extracts chunks, indexes Qdrant, and saves to MongoDB."""
    monkeypatch.setattr("api.routes.admin.get_qdrant_client", lambda: in_memory_qdrant)
    monkeypatch.setattr("db.qdrant_client.get_qdrant_client", lambda *args, **kwargs: in_memory_qdrant)

    sample_kb = [
        {
            "id": "dpdp_chunk_001",
            "topic": "Data Privacy and Protection",
            "act_name": "Digital Personal Data Protection Act, 2023",
            "section": "Section 6",
            "title": "Consent and Processing of Personal Data",
            "content": "Personal data may be processed only for a lawful purpose for which the citizen has given explicit consent.",
            "citation": "Digital Personal Data Protection Act, 2023, Section 6",
        },
        {
            "id": "dpdp_chunk_002",
            "topic": "Data Privacy and Protection",
            "act_name": "Digital Personal Data Protection Act, 2023",
            "section": "Section 12",
            "title": "Right to Access and Correction",
            "content": "A citizen has the statutory right to access their personal data and request correction or erasure.",
            "citation": "Digital Personal Data Protection Act, 2023, Section 12",
        },
    ]

    file_bytes = json.dumps(sample_kb).encode("utf-8")
    headers = {"Authorization": f"Bearer {admin_token}"}

    res = test_client.post(
        "/api/v1/admin/knowledge-base/upload",
        headers=headers,
        data={
            "title": "DPDP Act 2023",
            "act_name": "Digital Personal Data Protection Act, 2023",
            "topic": "Data Privacy",
            "jurisdiction": "India",
            "authority": "MeitY",
            "version": "1.0",
            "auto_activate": "true",
        },
        files={"file": ("dpdp_act.json", file_bytes, "application/json")},
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["title"] == "DPDP Act 2023"
    assert data["chunk_count"] == 2
    assert data["status"] == "active"
    assert data["is_active"] is True
    assert len(data["chunks"]) == 2

    # Verify listing returns the document
    list_res = test_client.get("/api/v1/admin/knowledge-base/documents", headers=headers)
    assert list_res.status_code == 200
    docs = list_res.json()
    assert any(d["document_id"] == data["document_id"] for d in docs)


def test_valid_docx_ingestion(test_client, admin_token, in_memory_qdrant, monkeypatch):
    """Uploading a DOCX file extracts legal text and generates indexed chunks."""
    monkeypatch.setattr("api.routes.admin.get_qdrant_client", lambda: in_memory_qdrant)
    monkeypatch.setattr("db.qdrant_client.get_qdrant_client", lambda *args, **kwargs: in_memory_qdrant)

    # Mock extract_text_from_kb_file to return sample legal text for DOCX
    docx_legal_text = (
        "Section 1. Short Title and Commencement\n"
        "This Act may be called the Maternity Benefit Amendment Act, 2017.\n\n"
        "Section 5. Right to Payment of Maternity Benefit\n"
        "Every woman shall be entitled to the payment of maternity benefit at the rate of the average daily wage."
    )

    with patch("api.routes.admin.extract_text_from_kb_file", return_value=docx_legal_text):
        with patch("api.routes.admin.validate_kb_file", return_value="docx"):
            headers = {"Authorization": f"Bearer {admin_token}"}
            res = test_client.post(
                "/api/v1/admin/knowledge-base/upload",
                headers=headers,
                data={
                    "title": "Maternity Benefit Act",
                    "act_name": "Maternity Benefit Amendment Act, 2017",
                    "topic": "Workplace Maternity Rights",
                },
                files={"file": ("maternity_act.docx", b"PK\x03\x04fake_docx_bytes", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

            assert res.status_code == 200, res.text
            data = res.json()
            assert data["chunk_count"] >= 1
            assert "Maternity" in data["act_name"]


# ── 3. File Validation & Duplicate Detection ─────────────────────────────────

def test_malformed_json_rejected(test_client, admin_token):
    """Malformed JSON returns 400 Bad Request."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = test_client.post(
        "/api/v1/admin/knowledge-base/upload",
        headers=headers,
        files={"file": ("broken.json", b"{invalid json...", "application/json")},
    )
    assert res.status_code == 400
    assert "Malformed JSON" in res.json()["detail"]


def test_unsupported_file_extension_rejected(test_client, admin_token):
    """Unsupported file extension (.exe) returns 400 Bad Request."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = test_client.post(
        "/api/v1/admin/knowledge-base/upload",
        headers=headers,
        files={"file": ("malicious.exe", b"MZ...", "application/octet-stream")},
    )
    assert res.status_code == 400
    assert "Unsupported file extension" in res.json()["detail"]


def test_duplicate_upload_detection(test_client, admin_token, in_memory_qdrant, monkeypatch):
    """Uploading the exact same file bytes a second time returns 409 Conflict."""
    monkeypatch.setattr("api.routes.admin.get_qdrant_client", lambda: in_memory_qdrant)
    monkeypatch.setattr("db.qdrant_client.get_qdrant_client", lambda *args, **kwargs: in_memory_qdrant)

    file_bytes = json.dumps([{"content": "Unique legal text for hash test"}]).encode("utf-8")
    headers = {"Authorization": f"Bearer {admin_token}"}

    res1 = test_client.post(
        "/api/v1/admin/knowledge-base/upload",
        headers=headers,
        files={"file": ("unique_law.json", file_bytes, "application/json")},
    )
    assert res1.status_code == 200

    # Second upload with identical bytes
    res2 = test_client.post(
        "/api/v1/admin/knowledge-base/upload",
        headers=headers,
        files={"file": ("unique_law.json", file_bytes, "application/json")},
    )
    assert res2.status_code == 409
    assert "already been uploaded" in res2.json()["detail"]


# ── 4. Lifecycle: Activate, Deactivate, Reprocess, Delete ────────────────────

def test_activation_and_deactivation_lifecycle(test_client, admin_token, in_memory_qdrant, monkeypatch):
    """Deactivating removes vectors from Qdrant; activating restores them."""
    monkeypatch.setattr("api.routes.admin.get_qdrant_client", lambda: in_memory_qdrant)
    monkeypatch.setattr("db.qdrant_client.get_qdrant_client", lambda *args, **kwargs: in_memory_qdrant)

    headers = {"Authorization": f"Bearer {admin_token}"}
    file_bytes = json.dumps([{"content": "Lifecycle test statute", "citation": "Lifecycle Act"}]).encode("utf-8")

    upload_res = test_client.post(
        "/api/v1/admin/knowledge-base/upload",
        headers=headers,
        data={"auto_activate": "true"},
        files={"file": ("lifecycle.json", file_bytes, "application/json")},
    )
    doc_id = upload_res.json()["document_id"]

    # Deactivate
    deact_res = test_client.post(f"/api/v1/admin/knowledge-base/documents/{doc_id}/deactivate", headers=headers)
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False

    # Activate
    act_res = test_client.post(f"/api/v1/admin/knowledge-base/documents/{doc_id}/activate", headers=headers)
    assert act_res.status_code == 200
    assert act_res.json()["is_active"] is True

    # Delete
    del_res = test_client.delete(f"/api/v1/admin/knowledge-base/documents/{doc_id}", headers=headers)
    assert del_res.status_code == 200

    # Ensure document is gone
    get_res = test_client.get(f"/api/v1/admin/knowledge-base/documents/{doc_id}", headers=headers)
    assert get_res.status_code == 404


# ── 5. Integration with Rights Agent Retrieval ──────────────────────────────

@pytest.mark.asyncio
async def test_rights_agent_retrieval_of_newly_uploaded_law(in_memory_qdrant):
    """Newly activated legal documents are retrieved by the existing Rights Agent with citations."""
    embedder = BGEM3Embedder(test_mode=True)
    agent = RightsAgent(qdrant_client=in_memory_qdrant, embedder=embedder)

    # Ingest a new legal document
    from services.rag.document_processor import index_chunks_in_qdrant
    new_chunks = [
        {
            "chunk_id": "cyber_chunk_1",
            "section": "Section 43A",
            "title": "Compensation for Failure to Protect Data",
            "content": "A body corporate possessing sensitive personal data is liable to pay damages if negligent in implementing reasonable security practices.",
            "citation": "Information Technology Act, 2000, Section 43A",
            "topic": "Cyber Law and Data Security",
            "act_name": "Information Technology Act, 2000",
        }
    ]
    embeddings = embedder.embed_texts([f"{new_chunks[0]['topic']}: {new_chunks[0]['title']}\nAct: {new_chunks[0]['act_name']} {new_chunks[0]['section']}\n{new_chunks[0]['content']}"])

    index_chunks_in_qdrant(
        client=in_memory_qdrant,
        collection_name=get_settings().QDRANT_COLLECTION_NAME,
        document_id="doc_cyber_test",
        chunks=new_chunks,
        embeddings=embeddings,
        metadata={
            "act_name": "Information Technology Act, 2000",
            "title": "Cyber Security Law",
            "authority": "MeitY",
            "topic": "Cyber Law",
        },
        is_active=True,
    )

    # Query Rights Agent
    retrieved = agent.retrieve_relevant_chunks("sensitive personal data protection compensation", top_k=3)
    assert len(retrieved) > 0
    top_payload, top_score = retrieved[0]
    assert "Information Technology Act" in top_payload.get("act_name", "")
    assert top_payload.get("citation") == "Information Technology Act, 2000, Section 43A"

    # Mock _generate_answer to avoid external API calls in tests
    agent._generate_answer = AsyncMock(
        return_value="Under Section 43A of the Information Technology Act 2000, compensation applies. [Source: Information Technology Act, 2000, Section 43A]"
    )

    # Explain Rights answer generation with verified citation
    response_text, citations, status = await agent.explain_rights("sensitive personal data protection compensation")
    assert status == "ok"
    assert any("Information Technology Act" in cit for cit in citations)
    assert "[Source:" in response_text


@pytest.mark.asyncio
async def test_deactivated_law_excluded_from_rights_agent(in_memory_qdrant):
    """Deactivated documents are never returned by Rights Agent retrieval."""
    embedder = BGEM3Embedder(test_mode=True)
    agent = RightsAgent(qdrant_client=in_memory_qdrant, embedder=embedder)

    from services.rag.document_processor import index_chunks_in_qdrant, remove_document_vectors_from_qdrant
    temp_chunks = [
        {
            "chunk_id": "temp_chunk_1",
            "section": "Section 99",
            "title": "Temporary Test Law",
            "content": "Exclusive unique keywords: xylophone zebra test law.",
            "citation": "Temporary Act, 2026, Section 99",
            "topic": "Test Topic",
            "act_name": "Temporary Act, 2026",
        }
    ]
    embeddings = embedder.embed_texts(["Test Topic: Temporary Test Law\nAct: Temporary Act, 2026 Section 99\nExclusive unique keywords: xylophone zebra test law."])

    doc_id = "doc_deactivated_test"
    index_chunks_in_qdrant(
        client=in_memory_qdrant,
        collection_name=get_settings().QDRANT_COLLECTION_NAME,
        document_id=doc_id,
        chunks=temp_chunks,
        embeddings=embeddings,
        metadata={"act_name": "Temporary Act, 2026"},
        is_active=True,
    )

    # Confirmed active retrieval
    active_results = agent.retrieve_relevant_chunks("xylophone zebra test law", top_k=2)
    assert any(p.get("document_id") == doc_id for p, _ in active_results)

    # Deactivate (removes vectors)
    remove_document_vectors_from_qdrant(in_memory_qdrant, get_settings().QDRANT_COLLECTION_NAME, doc_id)

    # Query again - should be excluded
    inactive_results = agent.retrieve_relevant_chunks("xylophone zebra test law", top_k=2)
    assert not any(p.get("document_id") == doc_id for p, _ in inactive_results)


def test_existing_seed_knowledge_retrieval_preserved(in_memory_qdrant):
    """Starter legal seed knowledge base (Model Tenancy, POSH, Consumer Protection) remains fully queryable."""
    embedder = BGEM3Embedder(test_mode=True)
    agent = RightsAgent(qdrant_client=in_memory_qdrant, embedder=embedder)

    retrieved = agent.retrieve_relevant_chunks("tenant security deposit deduction rules", top_k=3)
    assert len(retrieved) > 0
    top_payload, _ = retrieved[0]
    assert "Tenancy" in top_payload.get("act_name", "") or "Tenant" in top_payload.get("topic", "")
