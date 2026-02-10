# _DIR_META.md

## Architecture Vision
Contains all executable logic for the skill.
Separates concerns: Auth, Data Fetching, Visualization, and Intelligence.

## Member Index
- `garmin_auth.py`: [Core] Authentication handler (login/token mgmt).
- `garmin_data.py`: [Data] Raw data fetcher (JSON output).
- `garmin_chart.py`: [View] Interactive HTML chart generator.
- `garmin_fhir_adapter.py`: [Adapter] Converts Garmin data to HL7 FHIR standard.
- `garmin_intelligence.py`: [Intelligence] Bio-Entropy and Executive Readiness analysis.

> ⚠️ **Protocol**: Sync this file whenever directory content or responsibility shifts.
