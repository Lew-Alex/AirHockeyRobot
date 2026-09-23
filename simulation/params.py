"""Tunable parameters, with save and reload.

This module has no pygame in it on purpose: a parameter set is a file, and it has to be
loadable, editable and testable without a window. The panel in `panel.py` is the on-screen
way to change these, and `Params.apply` is the only place that writes them into the world.

Every parameter declares its own range, so the panel can draw a slider without knowing what
the parameter means, and so a hand-edited file cannot put the model into a state the
simulator cannot represent.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.json")
FORMAT_VERSION = 1


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    group: str
    minimum: float
    maximum: float
    default: float
    unit: str = ""
    decimals: int = 3

    def clamp(self, value: float) -> float:
        return min(max(float(value), self.minimum), self.maximum)

    def format(self, value: float) -> str:
        return f"{value:.{self.decimals}f}{(' ' + self.unit) if self.unit else ''}"


SCHEMA: tuple[Param, ...] = (
    # puck
    Param("puck_mass_kg", "puck mass", "puck", 0.005, 0.060, 0.022, "kg", 3),
    Param("puck_radius_m", "puck radius", "puck", 0.015, 0.045, 0.03175, "m", 4),
    # Both drag terms are decelerations, not forces, so neither is in newtons:
    #   deceleration = drag_per_s * speed + coulomb_mu * g
    # which makes drag_per_s [1/s] and coulomb_mu dimensionless. The force equivalent is
    # puck mass times that deceleration. See the README for the numbers.
    Param("puck_drag_per_s", "linear drag", "puck", 0.0, 1.0, 0.08, "1/s", 3),
    Param("puck_coulomb_mu", "sliding friction mu", "puck", 0.0, 0.20, 0.002, "", 3),
    # mallet
    Param("mallet_mass_kg", "driven mass", "mallet", 0.05, 3.0, 0.60, "kg", 2),
    Param("mallet_restitution", "restitution e", "mallet", 0.0, 1.0, 0.70, "", 2),
    Param("mallet_radius_m", "mallet radius", "mallet", 0.02, 0.06, 0.04125, "m", 4),
    Param("belt_speed_limit_m_s", "belt speed limit", "mallet", 1.0, 20.0, 10.0, "m/s", 2),
    # arena
    Param("wall_restitution", "wall restitution", "arena", 0.0, 1.0, 0.90, "", 2),
    Param("goal_width_in", "goal width", "arena", 3.0, 24.0, 12.0, "in", 1),
    # layer 2 control
    Param("controller_stiffness", "pointer stiffness", "input", 20.0, 2000.0, 400.0, "N/m", 0),
    Param("controller_damping", "pointer damping", "input", 0.0, 200.0, 40.0, "Ns/m", 0),
    Param("controller_max_force", "force ceiling", "input", 20.0, 2000.0, 400.0, "N", 0),
    # run loop
    Param("time_scale", "time scale", "run", 0.05, 2.0, 1.0, "x", 2),
    # the serve is deliberately gentle: it is the puck coming at you, and a slow first
    # look at the sim matters more than a fast one. Slide it up when you want pace.
    Param("serve_speed_m_s", "serve speed", "run", 0.0, 15.0, 1.0, "m/s", 2),
)

BY_KEY = {p.key: p for p in SCHEMA}
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(p.group for p in SCHEMA))


def defaults() -> dict[str, float]:
    return {p.key: p.default for p in SCHEMA}


class Params:
    """A parameter set: values, clamped, with a file to save them to."""

    def __init__(self, values: dict | None = None, path: str | None = None,
                 dirty: bool = False):
        self.values = defaults()
        self.path = path if path is not None else DEFAULT_PARAMS_PATH
        self.dirty = dirty
        if values:
            for key, value in values.items():
                if key in BY_KEY:
                    self.values[key] = BY_KEY[key].clamp(value)

    # ------------------------------------------------------------------ access
    def get(self, key: str) -> float:
        return self.values[key]

    def set(self, key: str, value: float, mark_dirty: bool = True) -> float:
        if key not in BY_KEY:
            raise KeyError(key)
        self.values[key] = BY_KEY[key].clamp(value)
        if mark_dirty:
            self.dirty = True
        return self.values[key]

    def __getitem__(self, key: str) -> float:
        return self.values[key]

    # ------------------------------------------------------------------ file
    def as_dict(self) -> dict:
        return {"version": FORMAT_VERSION,
                "note": "air hockey simulator parameters. Edited in the window or by hand.",
                "values": {k: self.values[k] for k in BY_KEY if k in self.values}}

    def save(self, path: str | None = None) -> str:
        target = path or self.path
        self.path = target
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w") as handle:
            json.dump(self.as_dict(), handle, indent=1, sort_keys=False)
            handle.write("\n")
        self.dirty = False
        return target

    @classmethod
    def load(cls, path: str | None = None) -> "Params":
        """Load from a file. A missing or unreadable file gives the defaults."""
        target = path or DEFAULT_PARAMS_PATH
        params = cls(path=target)
        try:
            with open(target) as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return params
        values = raw.get("values", raw) if isinstance(raw, dict) else {}
        if isinstance(values, dict):
            for key, value in values.items():
                if key in BY_KEY and isinstance(value, (int, float)):
                    params.values[key] = BY_KEY[key].clamp(value)
        params.dirty = False
        return params

    def reload(self) -> "Params":
        fresh = Params.load(self.path)
        self.values = fresh.values
        self.dirty = False
        return self

    def reset_to_defaults(self) -> None:
        self.values = defaults()
        self.dirty = True

    def copy(self) -> "Params":
        return Params(dict(self.values), self.path, self.dirty)

    # ------------------------------------------------------------------ effect
    def apply(self, world, controller=None) -> None:
        """Push the values into the live objects. Called every frame, so it must be cheap."""
        puck = world.puck
        puck.mass_kg = self.get("puck_mass_kg")
        puck.radius = puck.radius_m = self.get("puck_radius_m")
        puck.drag_per_s = self.get("puck_drag_per_s")
        puck.coulomb_mu = self.get("puck_coulomb_mu")

        world.arena.wall_restitution = self.get("wall_restitution")
        world.arena.goal_width_in = self.get("goal_width_in")

        for mallet in world.mallets:
            mallet.mass_kg = self.get("mallet_mass_kg")
            mallet.effective_mass_kg = self.get("mallet_mass_kg")
            mallet.restitution = self.get("mallet_restitution")
            mallet.radius = mallet.radius_m = self.get("mallet_radius_m")
            mallet.belt_speed_limit_m_s = self.get("belt_speed_limit_m_s")

        if controller is not None:
            controller.stiffness_n_per_m = self.get("controller_stiffness")
            controller.damping_n_per_m_s = self.get("controller_damping")
            controller.max_force_n = self.get("controller_max_force")


def load_or_default(path: str | None = None) -> Params:
    """The usual entry point: use the file if it is there, otherwise the defaults."""
    return Params.load(path)
