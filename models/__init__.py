from sqlalchemy import Column, Integer, String, Text, ForeignKey, DECIMAL, TIMESTAMP, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Any
from enum import Enum
from database import Base  # Assumes you have a database.py similar to User Service

# -------------------------------------------------------
# DATABASE MODELS (SQLAlchemy)
# -------------------------------------------------------
class Issue(Base):
    __tablename__ = "issues"

    issue_id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, index=True) # Stored from User Token
    title = Column(String(255), nullable=False)
    description = Column(Text)
    latitude = Column(Float, nullable=False) # Changed to Float for SQLite compat/simplicity
    longitude = Column(Float, nullable=False)
    image_url = Column(String(1024))
    
    # AI Enriched Fields
    category = Column(String(100), default="Uncategorized")
    priority = Column(String(50), default="medium")
    
    status = Column(String(50), default="open") # open, in_progress, resolved, rejected
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    comments = relationship("Comment", back_populates="issue")

class Comment(Base):
    __tablename__ = "comments"

    comment_id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(Integer, ForeignKey("issues.issue_id"))
    user_id = Column(Integer) # Stored from User Token
    text = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    issue = relationship("Issue", back_populates="comments")

class Confirmation(Base):
    __tablename__ = "confirmations"
    
    confirmation_id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(Integer, ForeignKey("issues.issue_id"))
    user_id = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())

# -------------------------------------------------------
# EXTERNAL SERVICE DTOs (Data Transfer Objects)
# -------------------------------------------------------
# Used to send data TO User Service or AI Service

class GamificationEventType(str, Enum):
    NEW_REPORT = "new_report"
    CONFIRM_ISSUE = "confirm_issue"
    REPORT_RESOLVED = "report_resolved"

class GamificationEventRequest(BaseModel):
    user_id: int
    event_type: GamificationEventType

class AIPriorityRequest(BaseModel):
    description: str

class AIPriorityResponse(BaseModel):
    priority: str
    reasoning: Optional[str] = None

class AICategorizeResponse(BaseModel):
    category: str
    confidence: float

# -------------------------------------------------------
# API SCHEMAS (Pydantic)
# -------------------------------------------------------

# --- Requests ---
class StatusUpdateRequest(BaseModel):
    status: str # "open", "in_progress", "resolved"

class CommentCreateRequest(BaseModel):
    text: str

# Note: Issue Creation is handled via Form Data, not JSON, so no Pydantic model needed for request body.

# --- Responses ---
class CommentResponse(BaseModel):
    comment_id: int
    user_id: int
    text: str
    created_at: Any

    model_config = ConfigDict(from_attributes=True)

class IssueResponse(BaseModel):
    issue_id: int
    title: str
    description: Optional[str]
    latitude: float
    longitude: float
    image_url: Optional[str]
    category: str
    status: str
    priority: str
    created_at: Any
    comments: List[CommentResponse] = []

    model_config = ConfigDict(from_attributes=True)

class IssueListResponse(BaseModel):
    issues: List[IssueResponse]