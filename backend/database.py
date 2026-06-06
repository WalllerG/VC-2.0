import os
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Use DATABASE_URL in production (e.g. Render Postgres); fall back to SQLite locally.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///users.db")
# Render hands out URLs starting with "postgres://" but SQLAlchemy needs "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    email = Column(String, primary_key=True)
    token = Column(Text)  # stores their Google token as JSON

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)