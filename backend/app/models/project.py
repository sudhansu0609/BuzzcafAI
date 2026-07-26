
from sqlalchemy.orm import Mapped,mapped_column
from app.db.base import Base
class Project(Base):
    __tablename__="projects"
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]
    status:Mapped[str]
