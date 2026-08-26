"""
Unit display conversion — the single engine behind D27 (`WAMA_DATA_WORLD.md §10`).

DOCTRINE. Data stays in ITS unit, always — `WamaVariables.unit` in a `.wdat`, `ParamSpec.unit`
in the function catalog. Conversion lives at the PRESENTATION layer only (preview, plots,
inspector), driven by a per-user preference, and an export that converts must SAY so in its
headers. This module never touches storage; it is the one place the presentation layer calls.

WHY PINT AND NOT A RATIO TABLE. Unit conversion is not multiplicative everywhere — °C → °F
carries an OFFSET, and a hand-rolled factor table renders 30 °C as 86.0 only until someone
"simplifies" it. Parsing ("km/h", "m/s²", "mph") is likewise a solved problem. Pint (BSD) is
the Python de-facto standard, in the same convention family the experiment-plan work already
cites (netCDF/CF, UCUM — `WAMA_DATA_WORLD.md §13.3`).

⚠ A missing sample stays missing: `None` (and NaN) traverse conversion as `None`, never as a
computed value — the same rule as `distances_a_point` (a hole is data, not a zero).
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

#: Unit systems a user can prefer. 'metric' keeps the source unit untouched (lab data is
#: acquired metric); 'imperial' remaps only the dimensions researchers actually read.
#: ⚠ Deliberately minimal — extend when a real screen needs a dimension, not before.
_SYSTEMS = {
    'metric': {},
    'imperial': {
        '[length]': 'mile',
        '[length] / [time]': 'mph',
        '[temperature]': 'degF',
    },
}

_registry = None


def registry():
    """The process-wide pint registry — built once (instantiation costs ~100 ms)."""
    global _registry
    if _registry is None:
        from pint import UnitRegistry
        _registry = UnitRegistry()
    return _registry


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and value != value)


def convert(value: Any, source: str, target: str) -> Optional[float]:
    """One value from `source` to `target` unit — offset units (°C → °F) included.

    `None` and NaN come back as `None` : a hole in the data must never become a number.
    Unknown units raise — a silent passthrough would display a value under a false label.
    """
    if _missing(value):
        return None
    if source == target:
        return float(value)
    return float(registry().Quantity(value, source).to(target).magnitude)


def convert_series(values: Sequence[Any], source: str, target: str) -> List[Optional[float]]:
    """A whole column, hole-preserving. The presentation layer decimates before converting."""
    return [convert(v, source, target) for v in values]


def display_unit(source: str, system: str = 'metric') -> str:
    """The unit to DISPLAY a value in, given the user's preferred unit system.

    Resolution goes through the DIMENSION of the source unit (speed, temperature…), so any
    speed unit lands on the system's speed unit. Unknown units, unknown dimensions and empty
    sources come back UNCHANGED — a preference must never make a column undisplayable.
    """
    table = _SYSTEMS.get(system)
    if not table or not source:
        return source
    try:
        dimension = str(registry().Unit(source).dimensionality)
    except Exception:
        return source
    return table.get(dimension, source)


def render(value: Any, source: str, system: str = 'metric', precision: int = 4) -> str:
    """Presentation string in the preferred system — `render(30, 'km/h', 'imperial')` → '18.64 mph'.

    A missing value renders as '' (the display layer shows its own placeholder, never a fake 0).
    """
    target = display_unit(source, system)
    converted = convert(value, source, target)
    if converted is None:
        return ''
    try:
        suffix = f"{registry().Unit(target):~P}" if target else ''
    except Exception:
        suffix = target
    number = f"{round(converted, precision):g}"
    return f"{number} {suffix}".strip()
