"""Official public model registry (ML-07): lifecycle for the live/Telegram model."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from backend.src.entity.base import Base


class PublicModelRegistryEntry(Base):
    """One registered model combination with lifecycle state.

    Only one row may be ``active`` at a time (enforced in service layer).
    Published predictions keep their original ``model_version`` / ``model_name``;
    registry changes never rewrite historical tips.
    """

    __tablename__ = "public_model_registry_entry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_version = Column(String(8), nullable=False, index=True)
    model_name = Column(String(64), nullable=False, index=True)
    # candidate | active | retired
    status = Column(String(16), nullable=False, default="candidate", index=True)
    activated_at = Column(DateTime, nullable=True)
    retired_at = Column(DateTime, nullable=True)
    approval_metrics_json = Column(Text, nullable=False, default="{}")
    motivation = Column(Text, nullable=True)
    artifacts_json = Column(Text, nullable=False, default="{}")
    supersedes_entry_id = Column(
        Integer,
        ForeignKey("public_model_registry_entry.id"),
        nullable=True,
    )
    walk_forward_run_id = Column(Integer, ForeignKey("walk_forward_run.id"), nullable=True)
    calibration_run_id = Column(Integer, ForeignKey("calibration_run.id"), nullable=True)
    created_at = Column(DateTime, nullable=False)
    created_by = Column(String(64), nullable=False, default="api")
    updated_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
