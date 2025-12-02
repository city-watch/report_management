import httpx
import jwt
import uuid
import os
from google.cloud import storage
from sqlalchemy import text, inspect
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import List, Optional
from jwt import PyJWTError

# Import your database setup
from database import get_db, engine, Base
from models import (
    Issue, Comment, Confirmation,
    IssueResponse, IssueListResponse, 
    CommentCreateRequest, CommentResponse,
    StatusUpdateRequest,
    GamificationEventRequest, GamificationEventType
)

# -------------------------------------------------------
# Configuration & Constants
# -------------------------------------------------------
SECRET_KEY = "super_secret_jwt_key"
ALGORITHM = "HS256"

# Service URLs
# USER_SERVICE_URL = "http://user-management-service:8000"
# AI_SERVICE_URL = "http://ai-orchestrator:8000"
AI_SERVICE_URL="http://localhost:8001"
USER_SERVICE_URL = "http://localhost:8002"

# Google Cloud Storage Configuration
GCS_BUCKET_NAME = "civic-app-issues-bucket"

# Duplicate Detection Threshold (in degrees)
# 0.0003 degrees is approximately 33 meters (100 feet)
DUPLICATE_RADIUS = 0.0003

app = FastAPI(title="Civic Report Management Service", version="1.0.0")

# Create Tables
Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{USER_SERVICE_URL}/api/v1/login")

# -------------------------------------------------------
# Auth Dependencies
# -------------------------------------------------------
def get_current_user_payload(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user_id(payload: dict = Depends(get_current_user_payload)) -> int:
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token missing user_id")
    return user_id

def get_current_city_employee(payload: dict = Depends(get_current_user_payload)) -> int:
    role = payload.get("role")
    if role not in ["Employee", "Admin", "City Employee"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Insufficient permissions. City Employee role required."
        )
    return payload.get("user_id")

# -------------------------------------------------------
# Storage Helper
# -------------------------------------------------------
async def upload_to_cloud(file: UploadFile) -> str:
    file_extension = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    unique_filename = f"{uuid.uuid4()}.{file_extension}"

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(unique_filename)
        
        await file.seek(0)
        blob.upload_from_file(file.file, content_type=file.content_type)
        return blob.public_url

    except Exception as e:
        print(f"❌ GCS Upload Failed: {e}")
        return "https://placehold.co/600x400?text=Upload+Failed"

# -------------------------------------------------------
# Health & DB Checks
# -------------------------------------------------------
@app.get("/")
def root():
    return {"message": "Civic Report Management Service is running."}

@app.get("/health/live")
def liveness_check():
    return {"status": "alive"}

@app.get("/db-check")
def db_check(db: Session = Depends(get_db)):
    try:
        inspector = inspect(db.get_bind())
        tables = inspector.get_table_names()
        db.execute(text("SELECT 1"))
        return {"status": "connected", "database_type": db.bind.name, "tables": tables}
    except Exception as e:
        return {"status": "error", "details": str(e)}

# -------------------------------------------------------
# Endpoints
# -------------------------------------------------------

@app.post("/api/v1/issues", status_code=status.HTTP_202_ACCEPTED)
async def submit_issue(
    title: str = Form(...),
    description: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    image: UploadFile = File(None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Orchestrates the creation of an issue:
    1. Uploads image to cloud (GCS).
    2. Calls AI Service for categorization.
    3. CHECK FOR DUPLICATES: If exists nearby + same category -> Confirm it.
    4. If new: Calls AI Priority -> Save to DB -> Trigger Gamification (New Report).
    """
    
    # 1. Image Handling
    image_url = None
    if image:
        image_url = await upload_to_cloud(image)

    # Defaults if AI fails
    detected_category = "Uncategorized"
    detected_priority = "medium"

    # Use AsyncClient for inter-service calls
    async with httpx.AsyncClient() as client:
        
        # 2. Call AI Service (Categorize)
        if image:
            try:
                # Reset file cursor or read from memory if needed
                await image.seek(0) 
                file_content = await image.read()
                
                # Send multipart request
                files = {'file': (image.filename, file_content, image.content_type)}
                ai_cat_response = await client.post(f"{AI_SERVICE_URL}/internal/ai/categorize", files=files)
                
                if ai_cat_response.status_code == 200:
                    detected_category = ai_cat_response.json().get("category", "Uncategorized")
            except Exception as e:
                print(f"AI Categorization service failed: {e}")

        # ---------------------------------------------------------
        # 3. Duplicate Detection Logic
        # ---------------------------------------------------------
        # Check for OPEN issues with SAME Category within small radius
        potential_duplicate = db.query(Issue).filter(
            Issue.status == "open",
            Issue.category == detected_category,
            Issue.latitude >= latitude - DUPLICATE_RADIUS,
            Issue.latitude <= latitude + DUPLICATE_RADIUS,
            Issue.longitude >= longitude - DUPLICATE_RADIUS,
            Issue.longitude <= longitude + DUPLICATE_RADIUS
        ).first()

        if potential_duplicate:
            print(f"Duplicate Found! Linking to existing Issue ID: {potential_duplicate.issue_id}")
            
            # Check if this specific user already confirmed it
            existing_conf = db.query(Confirmation).filter(
                Confirmation.issue_id == potential_duplicate.issue_id,
                Confirmation.user_id == user_id
            ).first()

            if not existing_conf:
                # A. Create Confirmation Record
                conf = Confirmation(issue_id=potential_duplicate.issue_id, user_id=user_id)
                db.add(conf)
                db.commit()

                # B. Trigger Gamification (Confirm Issue)
                try:
                    event_payload = {
                        "user_id": user_id, 
                        "event_type": GamificationEventType.CONFIRM_ISSUE.value
                    }
                    await client.post(f"{USER_SERVICE_URL}/internal/events", json=event_payload)
                except Exception as e:
                    print(f"Gamification service failed: {e}")

                return {
                    "message": "A similar issue was found nearby. We confirmed the existing report for you.",
                    "issue_id": potential_duplicate.issue_id,
                    "is_duplicate": True
                }
            else:
                return {
                    "message": "You have already reported/confirmed this issue.",
                    "issue_id": potential_duplicate.issue_id,
                    "is_duplicate": True
                }

        # ---------------------------------------------------------
        # 4. Process as New Report (No Duplicate Found)
        # ---------------------------------------------------------

        # Call AI Service (Priority)
        try:
            ai_prio_response = await client.post(
                f"{AI_SERVICE_URL}/internal/ai/assess-priority", 
                json={"description": description}
            )
            if ai_prio_response.status_code == 200:
                detected_priority = ai_prio_response.json().get("priority", "medium")
        except Exception as e:
            print(f"AI Priority service failed: {e}")

        # Save to DB
        new_issue = Issue(
            reporter_id=user_id,
            title=title,
            description=description,
            latitude=latitude,
            longitude=longitude,
            image_url=image_url,
            category=detected_category,
            priority=detected_priority,
            status="open"
        )
        db.add(new_issue)
        db.commit()
        db.refresh(new_issue)

        # Call User Service (Gamification - New Report)
        try:
            event_payload = {
                "user_id": user_id, 
                "event_type": GamificationEventType.NEW_REPORT.value
            }
            await client.post(f"{USER_SERVICE_URL}/internal/events", json=event_payload)
        except Exception as e:
            print(f"Gamification service failed: {e}")

    return {"message": "Your report is being processed.", "issue_id": new_issue.issue_id}


@app.get("/api/v1/issues", response_model=IssueListResponse)
def get_issues(
    status: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Issue)
    
    if status:
        query = query.filter(Issue.status == status)
    if category:
        query = query.filter(Issue.category == category)
        
    results = query.all()
    return {"issues": results}


@app.get("/api/v1/issues/{id}", response_model=IssueResponse)
def get_issue_detail(id: int, db: Session = Depends(get_db)):
    issue = db.query(Issue).filter(Issue.issue_id == id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@app.post("/api/v1/issues/{id}/confirm")
async def confirm_issue(id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """
    User confirms an existing issue. 
    Calls User Service -> Award Points (CONFIRM_ISSUE).
    """
    issue = db.query(Issue).filter(Issue.issue_id == id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if already confirmed by this user
    exists = db.query(Confirmation).filter(Confirmation.issue_id == id, Confirmation.user_id == user_id).first()
    if exists:
        return {"message": "You have already confirmed this issue."}

    # Create Confirmation
    conf = Confirmation(issue_id=id, user_id=user_id)
    db.add(conf)
    db.commit()

    # Call User Service (Gamification)
    async with httpx.AsyncClient() as client:
        try:
            event_payload = {
                "user_id": user_id, 
                "event_type": GamificationEventType.CONFIRM_ISSUE.value
            }
            await client.post(f"{USER_SERVICE_URL}/internal/events", json=event_payload)
        except Exception as e:
            print(f"Gamification service failed: {e}")

    return {"message": "Issue confirmed."}


@app.put("/api/v1/issues/{id}/status")
async def update_status(
    id: int, 
    payload: StatusUpdateRequest, 
    user_id: int = Depends(get_current_city_employee), # Requires Employee Role
    db: Session = Depends(get_db)
):
    """
    Updates status. If 'resolved', calls User Service -> Award Points (REPORT_RESOLVED).
    """
    issue = db.query(Issue).filter(Issue.issue_id == id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = payload.status
    db.commit()

    if payload.status == "resolved":
        # Call User Service (Gamification)
        # Note: We award points to the ORIGINAL reporter, not the employee closing it
        async with httpx.AsyncClient() as client:
            try:
                event_payload = {
                    "user_id": issue.reporter_id, 
                    "event_type": GamificationEventType.REPORT_RESOLVED.value
                }
                await client.post(f"{USER_SERVICE_URL}/internal/events", json=event_payload)
            except Exception as e:
                print(f"Gamification service failed: {e}")

    return {"id": id, "status": issue.status}


@app.post("/api/v1/issues/{id}/comments", status_code=status.HTTP_201_CREATED, response_model=CommentResponse)
def add_comment(
    id: int, 
    payload: CommentCreateRequest, 
    user_id: int = Depends(get_current_user_id), 
    db: Session = Depends(get_db)
):
    issue = db.query(Issue).filter(Issue.issue_id == id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    new_comment = Comment(
        issue_id=id,
        user_id=user_id,
        text=payload.text
    )
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return new_comment