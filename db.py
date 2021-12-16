from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session, util

Base = declarative_base()


class FileInfo(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    name = Column(String)
    size = Column(Integer)
    last_modified = Column(DateTime)
    is_dir = Column(Boolean)
    shared = Column(Boolean)
    indexing_finished = Column(Boolean, default=False)
    downloaded = Column(Boolean, default=False)
    uploaded = Column(Boolean, default=False)
    old_file_id = Column(Integer, unique=True)
    new_file_id = Column(Integer, unique=True, nullable=True)
    old_relative_path = Column(String, unique=True)
    new_relative_path = Column(String, unique=True, nullable=True)

    parent = relationship("FileInfo", backref="children", remote_side="FileInfo.id")

    def get_state(self):
        return util.object_state(self)

    def get_changed_attrs(self):
        changes = dict()

        state = self.get_state()
        for attr in state.attrs:
            hist = attr.load_history()

            if not hist.has_changes():
                continue

            # hist.deleted holds old value
            # hist.added holds new value
            changes[attr.key] = hist.added

        return changes

    def was_modified(self) -> bool:
        attrs = self.get_changed_attrs()

        # remove parent attribute, since parent attribute changes are reliably detected via parent_id
        if "parent" in attrs.keys():
            attrs.pop("parent")

        return len(attrs) != 0

    def update_new_relative_path(self, old_sub_folder, new_sub_folder):
        if not self.old_relative_path.startswith(old_sub_folder):
            raise Exception("old relative path does not start with old sub folder")

        self.new_relative_path = new_sub_folder + self.old_relative_path[len(old_sub_folder):]


def init_db(db_url: str) -> Session:
    engine = create_engine(db_url, echo=False, future=True)
    session_factory = sessionmaker(bind=engine)
    session: Session = session_factory()
    Base.metadata.create_all(engine)
    return session
