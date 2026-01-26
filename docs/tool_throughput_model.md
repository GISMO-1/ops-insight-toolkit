# Throughput Sensitivity Model

## Purpose
Estimate expected shift output using a simple time-loss model (minor stops + changeovers), then show which inputs most affect throughput with a +/-10% sensitivity scan.

## Inputs
- Nominal rate (units/hour)
- Minor stops per hour
- Average minor stop duration (minutes)
- Changeovers per shift
- Changeover duration (minutes)
- Shift length (hours)
- Staffing factor (default 1.0)

## Assumptions and Formulas
- Total shift minutes = shift length * 60.
- Minor-stop downtime = minor_stops_per_hour * avg_minor_stop_min * shift_length_hours.
- Changeover downtime = changeovers_per_shift * changeover_min.
- Available run time = shift minutes - (minor-stop downtime + changeover downtime).
- Expected output = nominal_rate * staffing_factor * (available run time / 60).
- Sensitivity table adjusts each parameter by +/-10% and ranks by absolute output impact.

## Example Command
```bash
python tools/throughput_model.py \
  --nominal-rate 120 \
  --minor-stops-per-hour 3 \
  --avg-minor-stop-min 2 \
  --changeovers-per-shift 1 \
  --changeover-min 25 \
  --shift-length-hours 12
```

## Example Output
```
Expected output per shift: 1,420.0 units
Downtime breakdown (minutes):
- Minor stops: 72.0
- Changeovers: 25.0
- Total lost time: 97.0

Sensitivity (+/-10% impact, units):
- nominal_rate: -10% 1,278.0 | +10% 1,562.0 | impact 142.0
- shift_length_hours: -10% 1,278.0 | +10% 1,562.0 | impact 142.0
- minor_stops_per_hour: -10% 1,444.0 | +10% 1,396.0 | impact 24.0
```
