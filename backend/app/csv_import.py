"""Parse and validate bioreactor observation CSV files."""

import csv
import io

from pydantic import ValidationError

from .models import Observation, RowError, UploadResult

MAX_ROWS = 10_000

FIELD_NAMES = list(Observation.model_fields)
REQUIRED_COLUMNS = [name for name, f in Observation.model_fields.items() if f.is_required()]


class CsvFormatError(ValueError):
    """The file as a whole cannot be processed (bad encoding, header problems, too large)."""


def parse_observations_csv(
    content: bytes, filename: str | None = None, target_experiment_id: str | None = None
) -> UploadResult:
    """Validate a CSV of observations.

    With `target_experiment_id` (uploading into a stored experiment) the experiment_id
    column becomes optional: empty cells take the target ID, and rows naming a different
    experiment are rejected rather than silently reassigned.
    """
    try:
        text = content.decode("utf-8-sig")  # tolerate the BOM Excel adds
    except UnicodeDecodeError:
        raise CsvFormatError("File is not valid UTF-8 text. Save the CSV with UTF-8 encoding.")

    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or not any(h.strip() for h in header):
        raise CsvFormatError("CSV file is empty or has no header row.")

    columns = [h.strip().lower() for h in header]
    duplicates = sorted({c for c in columns if c and columns.count(c) > 1})
    if duplicates:
        raise CsvFormatError(f"Duplicate column(s): {', '.join(duplicates)}.")
    required = [c for c in REQUIRED_COLUMNS if not (target_experiment_id and c == "experiment_id")]
    missing = [c for c in required if c not in columns]
    if missing:
        raise CsvFormatError(f"Missing required column(s): {', '.join(missing)}.")

    ignored = [c for c in columns if c and c not in FIELD_NAMES]
    observations: list[Observation] = []
    errors: list[RowError] = []
    total = 0

    for values in reader:
        line = reader.line_num
        if not any(v.strip() for v in values):
            continue  # skip blank lines
        total += 1
        if total > MAX_ROWS:
            raise CsvFormatError(f"Too many rows; the limit is {MAX_ROWS}.")

        if len(values) > len(columns):
            errors.append(RowError(
                row=line, field=None,
                message=f"Row has {len(values)} values but the header has {len(columns)} columns.",
            ))
            continue

        # Empty cells count as missing: required fields then fail, optional ones stay None.
        record = {
            col: val.strip()
            for col, val in zip(columns, values)
            if col in FIELD_NAMES and val.strip() != ""
        }
        if target_experiment_id:
            row_experiment = record.setdefault("experiment_id", target_experiment_id)
            if row_experiment != target_experiment_id:
                errors.append(RowError(
                    row=line, field="experiment_id", value=row_experiment,
                    message=f"Row belongs to experiment '{row_experiment}', not the selected '{target_experiment_id}'.",
                ))
                continue
        try:
            observations.append(Observation.model_validate(record))
        except ValidationError as exc:
            for err in exc.errors():
                field = str(err["loc"][0]) if err["loc"] else None
                errors.append(RowError(
                    row=line,
                    field=field,
                    message=err["msg"],
                    value=None if err["type"] == "missing" else str(err["input"]),
                ))

    return UploadResult(
        filename=filename,
        total_rows=total,
        accepted_count=len(observations),
        rejected_count=len({e.row for e in errors}),
        observations=observations,
        errors=errors,
        ignored_columns=ignored,
    )
