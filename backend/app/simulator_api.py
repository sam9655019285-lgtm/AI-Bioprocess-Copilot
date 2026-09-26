"""WebSocket endpoint streaming simulated bioreactor observations.

Each WebSocket connection owns one independent simulator; it stops when the client
disconnects. Protocol (JSON messages):

Client -> server
    {"action": "start", "config": {...SimulatorConfig}, "save_to": "EXP-ID"}
                                                          start a new run, or resume a stopped one;
                                                          "save_to" (optional) stores every generated
                                                          observation in that SIMULATED experiment
    {"action": "stop"}                                    pause streaming (state is kept)
    {"action": "reset"}                                   discard the run
    {"action": "disturb", "parameter": "temperature_c", "offset": 3}
                                                          SIMULATED DISTURBANCE (Phase 17): step-shift one value of
                                                          the current run (temperature_c, ph, dissolved_oxygen_percent,
                                                          agitation_rpm) to demonstrate live alerts

Server -> client
    {"type": "status", "status": "simulating" | "stopped", "data_source": "simulated", "run": {...} | null}
    {"type": "observation", "data_source": "simulated", "observation": {...Observation}, "saved": true | false | null}
    {"type": "alert", "event": "new" | "updated", "alert": {...}}
                                                          live alert from the existing anomaly rules (Phase 17,
                                                          see monitoring.py); sent after the observation that caused it
    {"type": "persistence_error", "message": "..."}      saving failed; the stream carries on
    {"type": "error", "message": "..."}
"""

import asyncio
import contextlib
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from . import repository as repo
from .db import session_scope
from .models import DataSource, Observation
from .monitoring import LiveMonitor
from .simulator import BioreactorSimulator, DisturbanceError, SimulatorConfig

DATA_SOURCE = "simulated"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulator", tags=["simulator"])

# Sessions currently connected; lets tests check that disconnects clean up.
active_sessions: set["SimulatorSession"] = set()


# --- Persistence (kept out of the simulation model; runs in a worker thread) ----------

class SaveTargetError(ValueError):
    pass


def check_save_target(experiment_id: str) -> float:
    """Validate that a new simulated run may be saved to this experiment; returns its scale."""
    with session_scope() as session:
        row = repo.get_experiment(session, experiment_id)
        if row is None:
            raise SaveTargetError(f"Experiment '{experiment_id}' not found.")
        if row.data_source != DataSource.SIMULATED.value:
            raise SaveTargetError(
                f"Experiment '{experiment_id}' has data source {row.data_source.upper()}; "
                "simulated data can only be saved to a SIMULATED experiment."
            )
        count = repo.count_observations(session, experiment_id)
        if count:
            raise SaveTargetError(
                f"Experiment '{experiment_id}' already has {count} observation(s). "
                "Create a new experiment for a new simulated run."
            )
        return row.scale_liters


def save_simulated_observation(experiment_id: str, observation: Observation) -> None:
    with session_scope() as session:
        repo.add_observations(session, experiment_id, [observation])


class SimulatorSession:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.simulator: BioreactorSimulator | None = None
        self.monitor: LiveMonitor | None = None  # live alerts for the current run (session-only)
        self.save_to: str | None = None
        self.task: asyncio.Task | None = None
        self.send_lock = asyncio.Lock()

    @property
    def running(self):
        return self.task is not None and not self.task.done()

    async def send(self, message: dict):
        async with self.send_lock:
            await self.websocket.send_json(message)

    async def send_status(self):
        run = None
        if self.simulator:
            run = {
                "experiment_id": self.simulator.experiment_id,
                **self.simulator.config.model_dump(exclude={"experiment_id"}),
                "saving_to": self.save_to,
            }
        await self.send({
            "type": "status",
            "status": "simulating" if self.running else "stopped",
            "data_source": DATA_SOURCE,
            "run": run,
        })

    async def handle(self, message: dict):
        action = message.get("action")
        if action == "start":
            if self.running:
                return await self.send_status()
            if self.simulator is None:
                try:
                    config = SimulatorConfig.model_validate(message.get("config") or {})
                except ValidationError as exc:
                    errors = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
                    return await self.send({"type": "error", "message": f"Invalid simulator config: {errors}"})
                save_to = message.get("save_to")
                if save_to:
                    try:
                        scale = await asyncio.to_thread(check_save_target, str(save_to))
                    except SaveTargetError as exc:
                        return await self.send({"type": "error", "message": str(exc)})
                    except Exception:
                        logger.exception("Could not check simulator save target")
                        return await self.send({"type": "error", "message": "Database error: could not check the experiment."})
                    # The stored experiment defines the run's ID and scale.
                    config = config.model_copy(update={"experiment_id": save_to, "volume_liters": scale})
                experiment_id = config.experiment_id or f"SIM-{config.volume_liters}L-{datetime.now():%Y%m%d-%H%M%S}"
                self.simulator = BioreactorSimulator(config, experiment_id)
                self.monitor = LiveMonitor(experiment_id)
                self.save_to = save_to or None
            self.task = asyncio.create_task(self._stream())
            await self.send_status()
        elif action == "stop":
            await self.cancel()
            await self.send_status()
        elif action == "reset":
            await self.cancel()
            self.simulator = None
            self.monitor = None
            self.save_to = None
            await self.send_status()
        elif action == "disturb":
            if self.simulator is None:
                return await self.send({"type": "error", "message": "Invalid disturbance: there is no simulated run to disturb."})
            try:
                self.simulator.apply_disturbance(message.get("parameter"), message.get("offset"))
            except DisturbanceError as exc:
                return await self.send({"type": "error", "message": str(exc)})
            await self.send_status()
        else:
            await self.send({"type": "error", "message": f"Unknown action: {action!r}"})

    async def _stream(self):
        sim = self.simulator
        while True:
            observation = sim.step()
            saved = None
            if self.save_to:
                try:
                    await asyncio.to_thread(save_simulated_observation, self.save_to, observation)
                    saved = True
                except Exception:
                    # Saving is best-effort: report it and keep the simulation running.
                    logger.exception("Could not save simulated observation")
                    saved = False
                    await self.send({
                        "type": "persistence_error",
                        "message": f"Could not save the observation at {observation.culture_time_hours} h "
                                   f"to '{self.save_to}'. The simulation continues.",
                    })
            events = self.monitor.add(observation, saved=saved is True)
            await self.send({
                "type": "observation",
                "data_source": DATA_SOURCE,
                "observation": observation.model_dump(),
                "saved": saved,
            })
            for event in events:
                await self.send(event)
            await asyncio.sleep(sim.config.interval_seconds)

    async def cancel(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None


@router.websocket("/ws")
async def simulator_ws(websocket: WebSocket):
    await websocket.accept()
    session = SimulatorSession(websocket)
    active_sessions.add(session)
    try:
        await session.send_status()
        while True:
            try:
                message = json.loads(await websocket.receive_text())
            except json.JSONDecodeError:
                await session.send({"type": "error", "message": "Messages must be JSON."})
                continue
            if not isinstance(message, dict):
                await session.send({"type": "error", "message": "Messages must be JSON objects."})
                continue
            await session.handle(message)
    except WebSocketDisconnect:
        pass
    finally:
        await session.cancel()
        active_sessions.discard(session)
