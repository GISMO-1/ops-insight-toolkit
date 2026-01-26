"""Throughput sensitivity model for shift-level output estimates."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ThroughputInputs:
    nominal_rate: float
    minor_stops_per_hour: float
    avg_minor_stop_min: float
    changeovers_per_shift: float
    changeover_min: float
    shift_length_hours: float
    staffing_factor: float = 1.0


class ThroughputModelError(ValueError):
    """Raised when throughput model inputs are invalid."""


def validate_inputs(inputs: ThroughputInputs) -> None:
    for field, value in inputs.__dict__.items():
        if value < 0:
            raise ThroughputModelError(f"{field} must be non-negative.")
    if inputs.shift_length_hours <= 0:
        raise ThroughputModelError("shift_length_hours must be greater than zero.")
    if inputs.nominal_rate <= 0:
        raise ThroughputModelError("nominal_rate must be greater than zero.")
    if inputs.staffing_factor <= 0:
        raise ThroughputModelError("staffing_factor must be greater than zero.")


def _downtime_minutes(inputs: ThroughputInputs) -> dict[str, float]:
    minor_stop_minutes = (
        inputs.minor_stops_per_hour * inputs.avg_minor_stop_min * inputs.shift_length_hours
    )
    changeover_minutes = inputs.changeovers_per_shift * inputs.changeover_min
    return {
        "minor_stops": minor_stop_minutes,
        "changeovers": changeover_minutes,
        "total": minor_stop_minutes + changeover_minutes,
    }


def compute_output(inputs: ThroughputInputs, allow_excess_downtime: bool = False) -> dict[str, float]:
    validate_inputs(inputs)
    shift_minutes = inputs.shift_length_hours * 60
    downtime = _downtime_minutes(inputs)
    if downtime["total"] > shift_minutes:
        if allow_excess_downtime:
            available_minutes = 0.0
        else:
            raise ThroughputModelError("Total downtime exceeds shift length.")
    else:
        available_minutes = shift_minutes - downtime["total"]

    effective_rate = inputs.nominal_rate * inputs.staffing_factor
    expected_units = effective_rate * (available_minutes / 60)

    return {
        "expected_units": expected_units,
        "available_minutes": available_minutes,
        **downtime,
    }


def compute_sensitivity(inputs: ThroughputInputs) -> list[dict[str, float]]:
    baseline = compute_output(inputs)["expected_units"]
    parameters = [
        "nominal_rate",
        "minor_stops_per_hour",
        "avg_minor_stop_min",
        "changeovers_per_shift",
        "changeover_min",
        "shift_length_hours",
        "staffing_factor",
    ]

    rows = []
    for param in parameters:
        original_value = getattr(inputs, param)
        delta = original_value * 0.1
        lower_inputs = replace(inputs, **{param: max(0.0, original_value - delta)})
        upper_inputs = replace(inputs, **{param: original_value + delta})

        lower_output = compute_output(
            lower_inputs, allow_excess_downtime=True
        )["expected_units"]
        upper_output = compute_output(
            upper_inputs, allow_excess_downtime=True
        )["expected_units"]
        impact = max(abs(lower_output - baseline), abs(upper_output - baseline))
        rows.append(
            {
                "parameter": param,
                "lower_output": lower_output,
                "upper_output": upper_output,
                "impact": impact,
            }
        )

    return sorted(rows, key=lambda row: row["impact"], reverse=True)


def render_report(inputs: ThroughputInputs) -> str:
    results = compute_output(inputs)
    sensitivity = compute_sensitivity(inputs)

    lines = [
        f"Expected output per shift: {results['expected_units']:,.1f} units",
        "Downtime breakdown (minutes):",
        f"- Minor stops: {results['minor_stops']:.1f}",
        f"- Changeovers: {results['changeovers']:.1f}",
        f"- Total lost time: {results['total']:.1f}",
        "",
        "Sensitivity (+/-10% impact, units):",
    ]

    for row in sensitivity:
        lines.append(
            "- {parameter}: -10% {lower:,.1f} | +10% {upper:,.1f} | impact {impact:,.1f}".format(
                parameter=row["parameter"],
                lower=row["lower_output"],
                upper=row["upper_output"],
                impact=row["impact"],
            )
        )

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estimate throughput and sensitivity.")
    parser.add_argument("--nominal-rate", type=float, required=True)
    parser.add_argument("--minor-stops-per-hour", type=float, required=True)
    parser.add_argument("--avg-minor-stop-min", type=float, required=True)
    parser.add_argument("--changeovers-per-shift", type=float, required=True)
    parser.add_argument("--changeover-min", type=float, required=True)
    parser.add_argument("--shift-length-hours", type=float, required=True)
    parser.add_argument("--staffing-factor", type=float, default=1.0)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])

    inputs = ThroughputInputs(
        nominal_rate=args.nominal_rate,
        minor_stops_per_hour=args.minor_stops_per_hour,
        avg_minor_stop_min=args.avg_minor_stop_min,
        changeovers_per_shift=args.changeovers_per_shift,
        changeover_min=args.changeover_min,
        shift_length_hours=args.shift_length_hours,
        staffing_factor=args.staffing_factor,
    )

    try:
        report = render_report(inputs)
    except ThroughputModelError as exc:
        print(f"Error: {exc}")
        return 1

    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
