from sqlalchemy.orm import Session
from app.db import SessionLocal

# Dependency
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()