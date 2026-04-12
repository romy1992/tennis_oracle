import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(BASE_DIR, "my_database.db")
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/tennis_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
