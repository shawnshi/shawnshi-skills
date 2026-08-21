# _DIR_META.md

## Architecture Vision
Contains all executable logic for the skill.
Separates concerns: Auth, Data Fetching, Query, Visualization, Intelligence, Activity Files, and FHIR Interop.

## Member Index
- `garmin_auth.py`: [Core] Authentication handler (login/token mgmt).
- `garmin_data.py`: [Data] Raw data fetcher — sleep, HRV, HR, BB, stress, activities, summary (JSON output).
- `garmin_sqlite_adapter.py`: [Data] Read-only (`mode=ro`) SQLite adapter for bounded local health-data extraction.
- `garmin_data_extended.py`: [Data] Extended metrics — SPO2, respiration, body composition, weight, floors, hydration, intensity minutes, training readiness, max metrics, endurance/hill scores.
- `garmin_query.py`: [Query] Point-in-time queries — "what was my HR at 3pm?". Supports HR, stress, BB, steps.
- `garmin_activity_files.py`: [Files] Download and parse FIT/GPX/TCX activity files. Extract GPS, elevation, pace, power, cadence.
- `garmin_chart.py`: [View] Interactive HTML chart generator (Chart.js). Produces Bio-Metric Audit dashboards.
- `garmin_intelligence.py`: [Intelligence] Full non-diagnostic analysis entrypoint; explicit `insight_cn --source ...` calls are delegated to the bounded reader.
- `garmin_bounded.py`: [Intelligence] Exact-window local/live descriptive reader; live mode loads tokens only in memory, skips Profile/Settings, and never persists refreshes or results.
- `sync_health_data.py`: [Data] Plan-bound GarminDB sync wrapper with explicit runner, date window, network and sync authorization gates; it never auto-installs dependencies or writes fallback JSON.
- `test_garmin_bounded_contract.py`: [Test] Capability-gate, exact-window, live fail-fast, provenance, no-hidden-read, and no-persistence regression coverage for the bounded primary insight path.
- `garmin_fhir_adapter.py`: [Adapter] Converts Garmin data to HL7 FHIR standard (Observations).

> ⚠️ **Protocol**: Sync this file whenever directory content or responsibility shifts.
