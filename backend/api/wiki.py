"""The company wiki: spaces, pages and version history."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import Document, DocumentVersion
from services import events
from services.identity import slugify

from . import serializers
from .companies import get_company

router = APIRouter(tags=["wiki"])


class DocumentIn(BaseModel):
    title: str
    body: str = ""
    space: str = "General"
    project_id: str | None = None
    parent_id: str | None = None


class DocumentPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    space: str | None = None


@router.get("/companies/{company_id}/documents")
def list_documents(company_id: str, space: str | None = None, db: Session = Depends(get_db)):
    get_company(db, company_id)
    query = (
        select(Document)
        .where(Document.company_id == company_id)
        .order_by(Document.space, Document.title)
    )
    if space:
        query = query.where(Document.space == space)
    rows = list(db.scalars(query))
    return {
        "spaces": sorted({row.space for row in rows}),
        "documents": [serializers.document(row, include_body=False) for row in rows],
    }


@router.post("/companies/{company_id}/documents", status_code=201)
def create_document(company_id: str, payload: DocumentIn, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    slug = slugify(payload.title, "page")
    if db.scalar(select(Document).where(Document.company_id == company.id, Document.slug == slug)):
        raise HTTPException(status_code=409, detail="A page with that title already exists.")

    document = Document(
        company_id=company.id,
        project_id=payload.project_id,
        space=payload.space,
        title=payload.title,
        slug=slug,
        body=payload.body,
        parent_id=payload.parent_id,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentVersion(document_id=document.id, version=1, body=payload.body, author_label="You")
    )
    events.record(
        db,
        company_id=company.id,
        project_id=payload.project_id,
        actor="You",
        kind="wiki.published",
        summary=f"created wiki page '{document.title}'",
        payload={"document_id": document.id, "slug": document.slug},
    )
    db.commit()
    return serializers.document(document)


@router.get("/documents/{document_id}")
def read_document(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Page not found.")
    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version.desc())
        )
    )
    return {
        **serializers.document(document),
        "history": [
            {
                "version": v.version,
                "author_label": v.author_label,
                "created_at": serializers.iso(v.created_at),
            }
            for v in versions
        ],
    }


@router.patch("/documents/{document_id}")
def update_document(document_id: str, payload: DocumentPatch, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Page not found.")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(document, key, value)
    if "body" in changes:
        document.version += 1
        db.add(
            DocumentVersion(
                document_id=document.id,
                version=document.version,
                body=document.body,
                author_label="You",
            )
        )
    db.add(document)
    events.record(
        db,
        company_id=document.company_id,
        project_id=document.project_id,
        actor="You",
        kind="wiki.published",
        summary=f"edited wiki page '{document.title}' (v{document.version})",
        payload={"document_id": document.id, "slug": document.slug},
    )
    db.commit()
    return serializers.document(document)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Page not found.")
    db.delete(document)
    db.commit()
