"""Software-only simulated bioreactor.

Generates plausible-looking cell-culture time series for visualisation and testing.
The model and its constants are illustrative; they are NOT calibrated to any real
cell line or process, and the output is not an experimental measurement.

Model (per step of `hours_per_step` simulated hours):
- cell density: logistic growth towards a carrying capacity
- temperature, agitation: mean-reverting noise around the initial setpoint
- pH: slow acidification as cell density rises, plus small noise
- DO: falls as oxygen demand (cell density) rises, plus small noise
- nutrient: depleted in proportion to cumulative growth
"""

import math
import random
from typing import Literal

from pydantic import BaseModel, Field

from .models import Observation

# Illustrative model constants (not biologically calibrated).
GROWTH_RATE_PER_HOUR = 0.04
MAX_CELL_DENSITY = 12.0  # ×10⁶ cells/mL
PH_DROP_AT_MAX_DENSITY = 0.25
DO_DROP_PER_DENSITY_UNIT = 2.5  # % air sat. per 10⁶ cells/mL
INITIAL_NUTRIENT_G_PER_L = 6.0
AERATION_VVM = 0.05
REVERSION = 0.2  # fraction of the gap to target closed each step (smooths values)


class SimulatorConfig(BaseModel):
    experiment_id: str | None = Field(default=None, min_length=1, max_length=100)
    volume_liters: Literal[1, 10, 100, 1000] = 1
    temperature_c: float = Field(default=37.0, ge=20, le=45, allow_inf_nan=False)
    ph: float = Field(default=7.1, ge=5, le=9, allow_inf_nan=False)
    dissolved_oxygen_percent: float = Field(default=50.0, ge=0, le=100, allow_inf_nan=False)
    agitation_rpm: float = Field(default=180.0, ge=0, le=2000, allow_inf_nan=False)
    cell_density: float = Field(default=0.5, gt=0, lt=MAX_CELL_DENSITY, allow_inf_nan=False)
    hours_per_step: float = Field(default=0.5, gt=0, le=24, description="Simulated hours advanced per step.")
    interval_seconds: float = Field(default=1.0, ge=0.05, le=10, description="Wall-clock time between steps.")
    seed: int | None = None


class BioreactorSimulator:
    def __init__(self, config: SimulatorConfig, experiment_id: str):
        self.config = config
        self.experiment_id = experiment_id
        self.rng = random.Random(config.seed)
        self.time_hours = 0.0
        self.temperature = config.temperature_c
        self.ph = config.ph
        self.do = config.dissolved_oxygen_percent
        self.agitation = config.agitation_rpm
        self.cells = config.cell_density
        self.nutrient = INITIAL_NUTRIENT_G_PER_L

    def _relax(self, value, target, noise_sd):
        return value + REVERSION * (target - value) + self.rng.gauss(0, noise_sd)

    def step(self) -> Observation:
        """Return the current state as an observation, then advance the simulation one step."""
        observation = Observation(
            experiment_id=self.experiment_id,
            culture_time_hours=round(self.time_hours, 2),
            temperature_c=round(self.temperature, 2),
            ph=round(self.ph, 3),
            dissolved_oxygen_percent=round(self.do, 1),
            agitation_rpm=round(self.agitation, 1),
            cell_density=round(self.cells, 3),
            nutrient_concentration=round(self.nutrient, 2),
            aeration_rate=AERATION_VVM,
        )
        self._advance()
        return observation

    def _advance(self):
        cfg = self.config
        dt = cfg.hours_per_step
        self.time_hours += dt

        # Logistic growth (exact solution over dt) with small multiplicative noise.
        k, x = MAX_CELL_DENSITY, self.cells
        grown = k / (1 + (k - x) / x * math.exp(-GROWTH_RATE_PER_HOUR * dt))
        self.cells = min(max(grown * (1 + self.rng.gauss(0, 0.004)), 1e-3), k)

        saturation = (self.cells - cfg.cell_density) / (k - cfg.cell_density)
        self.temperature = self._relax(self.temperature, cfg.temperature_c, 0.03)
        self.agitation = max(self._relax(self.agitation, cfg.agitation_rpm, 1.0), 0.0)
        self.ph = min(max(self._relax(self.ph, cfg.ph - PH_DROP_AT_MAX_DENSITY * saturation, 0.005), 0.0), 14.0)
        do_target = cfg.dissolved_oxygen_percent - DO_DROP_PER_DENSITY_UNIT * (self.cells - cfg.cell_density)
        self.do = min(max(self._relax(self.do, do_target, 0.4), 0.0), 100.0)
        self.nutrient = max(INITIAL_NUTRIENT_G_PER_L * (1 - 0.85 * saturation), 0.0)
