# _DIR_META.md

## Architecture Vision
Contains all executable logic for the skill.
Separates concerns: Auth, Data Fetching, Query, Visualization, Intelligence, Activity Files, and FHIR Interop.

## Member Index
- `garmin_auth.py`: [Core] Authentication handler (login/token mgmt).
- `garmin_data.py`: [Data] Raw data fetcher — sleep, HRV, HR, BB, stress, activities, summary (JSON output).
- `garmin_data_extended.py`: [Data] Extended metrics — SPO2, respiration, body composition, weight, floors, hydration, intensity minutes, training readiness, max metrics, endurance/hill scores.
- `garmin_query.py`: [Query] Point-in-time queries — "what was my HR at 3pm?". Supports HR, stress, BB, steps.
- `garmin_activity_files.py`: [Files] Download and parse FIT/GPX/TCX activity files. Extract GPS, elevation, pace, power, cadence.
- `garmin_chart.py`: [View] Interactive HTML chart generator (Chart.js). Produces Bio-Metric Audit dashboards.
- `garmin_intelligence.py`: [Intelligence] Bio-Entropy flu risk, Executive Readiness, full audit, and Chinese insight reports.
- `garmin_fhir_adapter.py`: [Adapter] Converts Garmin data to HL7 FHIR standard (Observations).

> ⚠️ **Protocol**: Sync this file whenever directory content or responsibility shifts.
