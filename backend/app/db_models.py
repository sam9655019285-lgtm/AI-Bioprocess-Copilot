"""SQLite tables. Validation lives in models.py; these classes only describe storage."""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentRow(SQLModel, table=True):
    __tablename__ = "experiments"

    id: int | None = Field(default=None, primary_key=True)
    experiment_id: str = Field(max_length=100, unique=True, index=True)
    name: str = Field(max_length=200)
    description: str | None = None
    scale_liters: float
    data_source: str = Field(max_length=20)  # a models.DataSource value
    created_at: datetime = Field(default_factory=utcnow)
    notes: str | None = None


class ObservationRow(SQLModel, table=True):
    """One observation; columns mirror models.Observation. Deleted with its experiment."""

    __tablename__ = "observations"

    id: int | None = Field(default=None, primary_key=True)
    experiment_id: str = Field(foreign_key="experiments.experiment_id", ondelete="CASCADE", index=True)
    culture_time_hours: float
    temperature_c: float
    ph: float
    dissolved_oxygen_percent: float
    agitation_rpm: float
    cell_density: float
    feed_rate: float | None = None
    nutrient_concentration: float | None = None
    aeration_rate: float | None = None
    notes: str | None = None
    recorded_at: datetime = Field(default_factory=utcnow)
