# LEXIS --- Admin Legal Knowledge Base

## Overview

This document describes the Admin-managed Legal Knowledge Base feature
for LEXIS. The feature extends the existing Admin Panel so authorized
administrators can upload legal documents and make their contents
available to the existing Rights Agent's Retrieval-Augmented Generation
(RAG) pipeline.

**Git branch:** `feature/admin-right-agent`

**Supported uploads:** PDF (`.pdf`), Word (`.docx`), and JSON (`.json`).

> Legal-content caution: a successful upload does not establish that a
> document is authentic, current, or applicable to a particular user.
> Administrators should verify the source, jurisdiction, effective date,
> and amendment status before activating legal content.

## What the feature does

-   Uploads legal documents through the Admin Panel.
-   Extracts text from supported file formats.
-   Splits extracted text into retrieval chunks while preserving useful
    legal section information.
-   Uses the existing embedding configuration and Qdrant collection.
-   Records document metadata and processing information in MongoDB.
-   Allows administrators to list and inspect documents, activate or
    deactivate them, reprocess them, and delete a document.
-   Makes active uploaded content available to the existing Rights Agent
    without creating a separate agent or replacing the existing seed
    JSON knowledge.

## Architecture

``` text
Admin uploads PDF / DOCX / JSON
              |
              v
Validate file and detect duplicates
              |
              v
Extract text and preserve legal sections
              |
              v
Split text into retrieval chunks
              |
              v
Generate embeddings using existing configuration
              |
              v
Index chunks in the existing Qdrant collection
              |
              v
Store document metadata/status in MongoDB
              |
              v
Existing Rights Agent retrieves relevant chunks
              |
              v
LLM generates an answer using retrieved context
```

MongoDB stores document records and lifecycle metadata. Qdrant stores
searchable vector chunks. The existing legal seed data should continue
to work.

## Admin API endpoints

The implementation report identifies the following endpoints. Confirm
the actual routes in the current source code and FastAPI OpenAPI page
before relying on them.

  -------------------------------------------------------------------------------------------------------------------
  Method                  Endpoint                                                            Purpose
  ----------------------- ------------------------------------------------------------------- -----------------------
  `POST`                  `/api/v1/admin/knowledge-base/upload`                               Upload and index a PDF,
                                                                                              DOCX, or JSON file

  `GET`                   `/api/v1/admin/knowledge-base/documents`                            List stored legal
                                                                                              documents

  `GET`                   `/api/v1/admin/knowledge-base/documents/{document_id}`              Inspect document
                                                                                              metadata and preview

  `POST`                  `/api/v1/admin/knowledge-base/documents/{document_id}/activate`     Activate/re-index a
                                                                                              document

  `POST`                  `/api/v1/admin/knowledge-base/documents/{document_id}/deactivate`   Deactivate a document

  `DELETE`                `/api/v1/admin/knowledge-base/documents/{document_id}`              Delete the document and
                                                                                              its indexed vectors

  `POST`                  `/api/v1/admin/knowledge-base/documents/{document_id}/reprocess`    Reprocess a stored
                                                                                              document
  -------------------------------------------------------------------------------------------------------------------

These endpoints should require an authenticated administrator, enforced
by the backend. Frontend route protection alone is not sufficient.

## Frontend

The Admin Panel includes a Legal Knowledge Base section intended to
provide:

-   File selection and upload.
-   Legal metadata entry.
-   Document list and processing status.
-   Text preview and chunk inspection.
-   Activation, deactivation, reprocessing, and deletion actions.
-   Visible success and error feedback.

The feature should reuse the existing Admin Panel layout and API client.

## Safety and lifecycle notes

-   Validate the file content, not only its extension or client-provided
    MIME type.
-   Enforce a reasonable upload size limit.
-   Detect duplicate uploads.
-   Keep uploaded files and secrets out of source control.
-   Deactivation must prevent retrieval of the document's chunks.
-   Deletion must target only the selected document's vectors; never
    delete the shared collection.
-   Reprocessing should not create duplicate chunks.
-   Failed extraction or indexing must not be reported as a successful
    activation.
-   Uploaded documents are untrusted content. Their text must not
    override system prompts or trusted application instructions.
-   Preserve the existing Rights Agent, seed JSON, authentication, and
    unrelated agents.

## Suggested official sample document

Use the **Consumer Protection Act, 2019** for an initial ingestion test:

-   Official PDF:
    https://www.indiacode.nic.in/bitstream/123456789/15256/1/eng201935.pdf
-   Official Act and Rules listing:
    https://consumeraffairs.gov.in/pages/consumer-protection-acts

Suggested metadata:

  Field          Value
  -------------- --------------------------------------------------
  Title          Consumer Protection Act, 2019
  Jurisdiction   India --- Central
  Authority      Government of India, Ministry of Law and Justice
  Version        Original Act, 2019
  Source         Official India Code PDF URL above

**Important:** the original 2019 Act PDF is useful for testing ingestion
and retrieval. It should not automatically be represented as a
consolidated version containing every subsequent amendment. Verify
current amendments and applicability before relying on it as current
legal guidance.

## Manual verification checklist

1.  Start the backend using the project's documented command.
2.  Start the frontend using `npm run dev`.
3.  Sign in with the authorized admin account.
4.  Open **Admin Panel → Legal Knowledge Base**.
5.  Upload a test PDF and verify that processing completes.
6.  Inspect the extracted text and document metadata.
7.  Confirm the document has indexed chunks.
8.  Ask the Rights Agent a question that should match a section in the
    uploaded document.
9.  Check that the response uses relevant retrieved context and provides
    a source/section reference where supported.
10. Deactivate the document and verify that its chunks are no longer
    retrieved.
11. Verify that the original JSON seed knowledge and citizen OTP login
    still work.

## Automated checks

Run the checks from the correct project directory and use the project's
active virtual environment.

Example commands, adjusting paths to match the repository:

``` powershell
# Backend
cd backend
.\venv\Scripts\pytest.exe tests/test_admin_knowledge_base.py -v
.\venv\Scripts\pytest.exe tests/unit/test_admin_panel.py tests/unit/test_rights_agent.py -v

# Frontend
cd ..\frontend
npm run build
```

Record the actual output and test results from your current checkout. Do
not treat earlier logs as proof that a later code revision still passes.

## Files identified in the implementation report

The implementation report says the feature touches or adds the following
files. Check `git status` and the repository before committing:

-   `backend/models/knowledge_base.py`
-   `backend/services/rag/document_processor.py`
-   `backend/api/routes/admin.py`
-   `backend/agents/rights_agent/agent.py`
-   `frontend/src/services/api.js`
-   `frontend/src/pages/AdminDashboard.jsx`
-   `frontend/src/pages/AdminDashboard.css`
-   `backend/tests/test_admin_knowledge_base.py`
-   `.gitignore`

It also reports a correction in `frontend/src/App.jsx` for invalid
Markdown code fences.

## Before merging

-   Review the complete Git diff.
-   Confirm that no credentials, uploaded legal files, or generated data
    were added to Git.
-   Run the automated tests and frontend build on the current branch.
-   Test admin authorization and citizen access.
-   Verify upload, retrieval, deactivation, and deletion against the
    actual local services.
-   Ask a domain-aware reviewer to verify legal source and amendment
    status before using uploaded documents for real legal guidance.

------------------------------------------------------------------------

*Maintainer note: update this document if endpoint paths, storage
behavior, supported formats, or tests change.*
