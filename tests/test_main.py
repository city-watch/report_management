import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import respx
from httpx import Response
import os
import main

# Set dummy environment variables for testing
os.environ['SECRET_KEY'] = 'super_secret_jwt_key'
os.environ['ALGORITHM'] = 'HS256'
os.environ['USER_SERVICE_URL'] = "http://localhost:8002"
os.environ['AI_SERVICE_URL'] = "http://localhost:8001"
os.environ['GCS_BUCKET_NAME'] = "civic-app-issues-bucket"


from main import app, get_db
from database import Base

# -------------------------------------------------------
# Test Database Setup
# -------------------------------------------------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables in the test database
Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# -------------------------------------------------------
# Pytest Fixtures
# -------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    """Create a new database session for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client that uses the override_get_db dependency."""
    
    def override_get_db_for_client():
        try:
            yield db_session
        finally:
            pass 

    app.dependency_overrides[get_db] = override_get_db_for_client
    with TestClient(app) as c:
        yield c
    # Clean up dependency overrides
    app.dependency_overrides = {}


@pytest.fixture
def mock_auth_token():
    """Creates a valid JWT token for a regular user."""
    import jwt
    payload = {"user_id": 1, "role": "User"}
    return jwt.encode(payload, os.environ['SECRET_KEY'], algorithm=os.environ['ALGORITHM'])

@pytest.fixture
def mock_employee_auth_token():
    """Creates a valid JWT token for a city employee."""
    import jwt
    payload = {"user_id": 99, "role": "City Employee"}
    return jwt.encode(payload, os.environ['SECRET_KEY'], algorithm=os.environ['ALGORITHM'])

# -------------------------------------------------------
# Basic Tests
# -------------------------------------------------------

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Civic Report Management Service is running."}

def test_liveness_check(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

def test_db_check(client):
    response = client.get("/db-check")
    assert response.status_code == 200
    assert response.json()["status"] == "connected"

# -------------------------------------------------------
# Issue Endpoint Tests
# -------------------------------------------------------

@respx.mock
def test_submit_new_issue_with_image(client, mock_auth_token, db_session, monkeypatch):
    # Mock external services
    ai_categorize_route = respx.post("http://localhost:8001/internal/ai/categorize").mock(
        return_value=Response(200, json={"category": "Pothole"})
    )
    ai_priority_route = respx.post("http://localhost:8001/internal/ai/assess-priority").mock(
        return_value=Response(200, json={"priority": "high"})
    )
    gamification_route = respx.post("http://localhost:8002/internal/events").mock(
        return_value=Response(200, json={"message": "Event received"})
    )
    
    # Mock GCS upload
    async def mock_upload_to_cloud(file):
        return "http://fake-gcs-url.com/image.jpg"
    
    monkeypatch.setattr(main, "upload_to_cloud", mock_upload_to_cloud)
    
    headers = {"Authorization": f"Bearer {mock_auth_token}"}
    
    # Create a dummy file for upload
    dummy_image = b"fakeimagedata"
    
    response = client.post(
        "/api/v1/issues",
        headers=headers,
        data={
            "title": "Giant Pothole",
            "description": "A very large pothole on Main St.",
            "latitude": 40.7128,
            "longitude": -74.0060,
        },
        files={"image": ("test.jpg", dummy_image, "image/jpeg")},
    )

    assert response.status_code == 202
    assert response.json()["message"] == "Your report is being processed."
    assert "issue_id" in response.json()
    
    from models import Issue
    issue = db_session.query(Issue).first()
    assert issue is not None
    assert issue.title == "Giant Pothole"
    assert issue.category == "Pothole"
    assert issue.priority == "high"
    assert issue.image_url == "http://fake-gcs-url.com/image.jpg"
    assert ai_categorize_route.called
    assert ai_priority_route.called
    assert gamification_route.called


@respx.mock
def test_get_issues(client, db_session):
    from models import Issue
    # Add some data to the test database
    db_session.add(Issue(reporter_id=1, title="Issue 1", description="Desc 1", latitude=1, longitude=1, category="Graffiti", status="open"))
    db_session.add(Issue(reporter_id=2, title="Issue 2", description="Desc 2", latitude=2, longitude=2, category="Pothole", status="open"))
    db_session.add(Issue(reporter_id=3, title="Issue 3", description="Desc 3", latitude=3, longitude=3, category="Graffiti", status="resolved"))
    db_session.commit()

    # Test no filters
    response = client.get("/api/v1/issues")
    assert response.status_code == 200
    assert len(response.json()["issues"]) == 3

    # Test filter by status
    response = client.get("/api/v1/issues?status=open")
    assert response.status_code == 200
    assert len(response.json()["issues"]) == 2

    # Test filter by category
    response = client.get("/api/v1/issues?category=Graffiti")
    assert response.status_code == 200
    assert len(response.json()["issues"]) == 2

    # Test filter by both
    response = client.get("/api/v1/issues?status=open&category=Graffiti")
    assert response.status_code == 200
    assert len(response.json()["issues"]) == 1
    assert response.json()["issues"][0]["title"] == "Issue 1"

def test_get_issue_detail(client, db_session):
    from models import Issue
    issue = Issue(reporter_id=1, title="Detail Test", description="...", latitude=1, longitude=1)
    db_session.add(issue)
    db_session.commit()

    response = client.get(f"/api/v1/issues/{issue.issue_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Detail Test"

    response = client.get("/api/v1/issues/999")
    assert response.status_code == 404

@respx.mock
def test_confirm_issue(client, mock_auth_token, db_session):
    from models import Issue
    issue = Issue(reporter_id=2, title="Confirm Test", description="...", latitude=1, longitude=1)
    db_session.add(issue)
    db_session.commit()

    gamification_route = respx.post("http://localhost:8002/internal/events").mock(
        return_value=Response(200, json={"message": "Event received"})
    )

    headers = {"Authorization": f"Bearer {mock_auth_token}"}
    response = client.post(f"/api/v1/issues/{issue.issue_id}/confirm", headers=headers)
    
    assert response.status_code == 200
    assert response.json()["message"] == "Issue confirmed."
    assert gamification_route.called

    from models import Confirmation
    conf = db_session.query(Confirmation).first()
    assert conf is not None
    assert conf.issue_id == issue.issue_id
    assert conf.user_id == 1 # From mock_auth_token

    # Test confirming again
    response = client.post(f"/api/v1/issues/{issue.issue_id}/confirm", headers=headers)
    assert response.status_code == 200
    assert response.json()["message"] == "You have already confirmed this issue."


@respx.mock
def test_update_status(client, mock_employee_auth_token, db_session):
    from models import Issue
    issue = Issue(reporter_id=1, title="Status Test", description="...", latitude=1, longitude=1, status="open")
    db_session.add(issue)
    db_session.commit()

    gamification_route = respx.post("http://localhost:8002/internal/events").mock(
        return_value=Response(200, json={"message": "Event received"})
    )

    headers = {"Authorization": f"Bearer {mock_employee_auth_token}"}
    
    # Test updating to 'in_progress'
    response = client.put(f"/api/v1/issues/{issue.issue_id}/status", headers=headers, json={"status": "in_progress"})
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert not gamification_route.called # Should not be called for 'in_progress'

    # Test updating to 'resolved'
    response = client.put(f"/api/v1/issues/{issue.issue_id}/status", headers=headers, json={"status": "resolved"})
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert gamification_route.called

def test_add_comment(client, mock_auth_token, db_session):
    from models import Issue
    issue = Issue(reporter_id=2, title="Comment Test", description="...", latitude=1, longitude=1)
    db_session.add(issue)
    db_session.commit()
    
    headers = {"Authorization": f"Bearer {mock_auth_token}"}
    response = client.post(
        f"/api/v1/issues/{issue.issue_id}/comments",
        headers=headers,
        json={"text": "This is a comment"}
    )

    assert response.status_code == 201
    assert response.json()["text"] == "This is a comment"
    assert response.json()["user_id"] == 1 # From mock_auth_token

    from models import Comment
    comment = db_session.query(Comment).first()
    assert comment is not None
    assert comment.text == "This is a comment"

@respx.mock
def test_submit_duplicate_issue(client, mock_auth_token, db_session, monkeypatch):
    from models import Issue
    # Pre-existing issue
    db_session.add(Issue(
        issue_id=100,
        title="Existing Pothole", 
        description="...", 
        latitude=40.7130, 
        longitude=-74.0058,
        category="Pothole",
        status="open",
        reporter_id=50
    ))
    db_session.commit()

    async def mock_upload_to_cloud(file):
        return "http://fake-gcs-url.com/image.jpg"
    
    monkeypatch.setattr(main, "upload_to_cloud", mock_upload_to_cloud)

    # Mock AI service to return the same category
    with respx.mock as mock:
        mock.post("http://localhost:8001/internal/ai/categorize").mock(
            return_value=Response(200, json={"category": "Pothole"})
        )
        gamification_route = mock.post("http://localhost:8002/internal/events").mock(
            return_value=Response(200, json={"message": "Event received"})
        )

        headers = {"Authorization": f"Bearer {mock_auth_token}"}
        dummy_image = b"fakedata"
        response = client.post(
            "/api/v1/issues",
            headers=headers,
            data={
                "title": "Another Pothole",
                "description": "A pothole at almost the same location.",
                "latitude": 40.7129, # Very close to the existing one
                "longitude": -74.0059,
            },
            files={"image": ("test.jpg", dummy_image, "image/jpeg")},
        )
        
        assert response.status_code == 202 
        assert response.json()["message"] == "A similar issue was found nearby. We confirmed the existing report for you."
        assert response.json()["issue_id"] == 100
        assert response.json()["is_duplicate"] is True
        assert gamification_route.called
        
        from models import Confirmation
        # Check that a confirmation was created for user 1 on issue 100
        conf = db_session.query(Confirmation).filter_by(user_id=1, issue_id=100).first()
        assert conf is not None
        
        # Ensure a new issue was NOT created
        issue_count = db_session.query(Issue).count()
        assert issue_count == 1
