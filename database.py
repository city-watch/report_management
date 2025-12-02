import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# --- 1. Load Environment Variables ---
# Loads the .env file so os.getenv can find DATABASE_URL
load_dotenv()

# --- 2. Get Connection String ---
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL is not set in the environment. Please create a .env file.")

# --- 3. Create SQLAlchemy Engine ---
# echo=True prints SQL statements to the console (useful for debugging)
engine = create_engine(DATABASE_URL, echo=False)

# --- 4. Create Session Factory ---
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- 5. Declare Base for ORM Models ---
# Your models.py will import this Base to define classes
Base = declarative_base()

# --- 6. FastAPI Dependency for Database Session ---
def get_db():
    """
    Dependency that provides a database session for each request.
    Ensures the session is properly closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
