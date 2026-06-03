import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "../../../properties/config.env"
)
load_dotenv(dotenv_path=CONFIG_PATH)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(BASE_DIR, "my_database.db")
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/tennis_db"
DATABASE_URL = os.getenv("DATABASE_URL", os.getenv(
    "DATABASE_SOURCE_URL", DEFAULT_DATABASE_URL
))

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
