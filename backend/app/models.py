"""Data model for a single bioreactor observation.

Validation in this phase is about type/format only. The few numeric bounds used
are physical/definitional (no negative times, rates or densities; pH within 0-14),
not biological operating limits.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _field(*, unit=None, **kwargs):
    extra = {"unit": unit} if unit else None
    return Field(allow_inf_nan=False, json_schema_extra=extra, **kwargs)


class Observation(BaseModel):
    """One time-point measurement from a bioreactor run."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Required
    experiment_id: str = Field(
        min_length=1, max_length=100, title="Experiment ID",
        description="Identifier of the run/batch this observation belongs to.",
    )
    culture_time_hours: float = _field(
        ge=0, unit="h", title="Culture time", description="Time since inoculation."
    )
    temperature_c: float = _field(unit="°C", title="Temperature")
    ph: float = _field(ge=0, le=14, title="pH")
    dissolved_oxygen_percent: float = _field(
        ge=0, unit="% air sat.", title="Dissolved oxygen",
        description="Dissolved oxygen as percent of air saturation.",
    )
    agitation_rpm: float = _field(ge=0, unit="rpm", title="Agitation")
    cell_density: float = _field(
        ge=0, unit="×10⁶ cells/mL", title="Cell density",
        description="Viable cell density.",
    )

    # Optional
    feed_rate: float | None = _field(default=None, ge=0, unit="mL/h", title="Feed rate")
    nutrient_concentration: float | None = _field(
        default=None, ge=0, unit="g/L", title="Nutrient concentration",
        description="E.g. glucose concentration in the medium.",
    )
    aeration_rate: float | None = _field(
        default=None, ge=0, unit="vvm", title="Aeration rate",
        description="Gas flow in volumes of gas per culture volume per minute.",
    )
    notes: str | None = Field(default=None, max_length=1000, title="Notes")


class ObservationResponse(BaseModel):
    message: str
    observation: Observation


class RowError(BaseModel):
    row: int = Field(description="CSV line number (the header is line 1).")
    field: str | None
    message: str
    value: str | None = None


class UploadResult(BaseModel):
    filename: str | None
    total_rows: int
    accepted_count: int
    rejected_count: int
    observations: list[Observation]
    errors: list[RowError]
    ignored_columns: list[str]


class SchemaField(BaseModel):
    name: str
    label: str
    type: str
    required: bool
    unit: str | None = None
    description: str | None = None
    minimum: float | None = None
    maximum: float | None = None


# --- Stored experiments (Phase 4) -------------------------------------------------

# Reserved because they are fixed paths under /api/experiments/.
RESERVED_EXPERIMENT_IDS = {"schema", "upload", "observations"}


class DataSource(str, Enum):
    """Where an experiment's observations come from. Add e.g. LIVE here later."""

    MANUAL = "manual"
    CSV = "csv"
    SIMULATED = "simulated"


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    experiment_id: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="Unique ID; letters, digits, '.', '_' and '-' (used in URLs).",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    scale_liters: float = Field(gt=0, allow_inf_nan=False, description="Working scale of the experiment, e.g. 1, 10, 100, 1000 L.")
    data_source: DataSource
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("experiment_id")
    @classmethod
    def not_reserved(cls, value: str) -> str:
        if value.lower() in RESERVED_EXPERIMENT_IDS:
            raise ValueError(f"'{value}' is reserved; choose another experiment ID")
        return value


class ExperimentRead(BaseModel):
    experiment_id: str
    name: str
    description: str | None
    scale_liters: float
    data_source: DataSource
    created_at: datetime
    notes: str | None
    observation_count: int


class ObservationCreate(Observation):
    """Observation posted to a stored experiment; experiment_id comes from the URL."""

    experiment_id: str | None = Field(default=None, min_length=1, max_length=100)


class ObservationRead(Observation):
    id: int
    recorded_at: datetime


class SavedObservationResponse(BaseModel):
    message: str
    observation: ObservationRead
    observation_count: int


class SavedUploadResult(UploadResult):
    experiment_id: str
    saved_count: int


class DeleteResult(BaseModel):
    message: str
    experiment_id: str
    deleted_observations: int
