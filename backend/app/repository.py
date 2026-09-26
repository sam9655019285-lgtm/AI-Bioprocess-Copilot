"""Database access for experiments and their observations."""

from datetime import timezone

from sqlalchemy import delete, func
from sqlmodel import Session, select

from .db_models import ExperimentRow, ObservationRow
from .models import ExperimentCreate, ExperimentRead, Observation, ObservationRead


def _as_utc(value):
    # SQLite drops tzinfo; everything is stored in UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def to_experiment_read(row: ExperimentRow, observation_count: int) -> ExperimentRead:
    return ExperimentRead(
        **row.model_dump(exclude={"id", "created_at"}),
        created_at=_as_utc(row.created_at),
        observation_count=observation_count,
    )


def to_observation_read(row: ObservationRow) -> ObservationRead:
    return ObservationRead(**row.model_dump(exclude={"recorded_at"}), recorded_at=_as_utc(row.recorded_at))


def get_experiment(session: Session, experiment_id: str) -> ExperimentRow | None:
    return session.exec(select(ExperimentRow).where(ExperimentRow.experiment_id == experiment_id)).first()


def count_observations(session: Session, experiment_id: str) -> int:
    query = select(func.count()).select_from(ObservationRow).where(ObservationRow.experiment_id == experiment_id)
    return session.exec(query).one()


def create_experiment(session: Session, data: ExperimentCreate) -> ExperimentRow:
    row = ExperimentRow(**data.model_dump(mode="json"))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_experiments(session: Session) -> list[ExperimentRead]:
    counts = (
        select(ObservationRow.experiment_id, func.count().label("n"))
        .group_by(ObservationRow.experiment_id)
        .subquery()
    )
    query = (
        select(ExperimentRow, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.experiment_id == ExperimentRow.experiment_id)
        .order_by(ExperimentRow.created_at.desc(), ExperimentRow.id.desc())
    )
    return [to_experiment_read(row, n) for row, n in session.exec(query).all()]


def add_observations(session: Session, experiment_id: str, observations: list[Observation]) -> list[ObservationRow]:
    """Save observations to an experiment in one transaction (all or nothing)."""
    rows = [ObservationRow(**{**obs.model_dump(), "experiment_id": experiment_id}) for obs in observations]
    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def list_observations(session: Session, experiment_id: str, limit: int | None = None) -> list[ObservationRow]:
    """Observations in chronological order (culture time, then insertion); all of them if `limit` is None."""
    query = (
        select(ObservationRow)
        .where(ObservationRow.experiment_id == experiment_id)
        .order_by(ObservationRow.culture_time_hours, ObservationRow.id)
        .limit(limit)
    )
    return list(session.exec(query).all())


def delete_experiment(session: Session, row: ExperimentRow) -> int:
    """Delete an experiment and all its observations in one transaction; returns observations deleted."""
    result = session.execute(delete(ObservationRow).where(ObservationRow.experiment_id == row.experiment_id))
    session.delete(row)
    session.commit()
    return result.rowcount
