
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
DATABASE_URL="postgresql://buzzcaf:buzzcaf@db:5432/buzzcaf"
engine=create_engine(DATABASE_URL)
SessionLocal=sessionmaker(bind=engine)
