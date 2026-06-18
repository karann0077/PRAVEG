# Architecture V2 Subagent Orchestration

This file tracks the eight production-grade upgrade subtasks and their assigned workers.

## Running Workers

1. Zone-Type & Proximity Features
   - Agent: Sartre
   - ID: `019ed8c4-6630-7ba3-9c64-f306b45d70da`
   - Scope: `parking_engine/spatial_context.py`

2. Legal Parking Overflow Modeling
   - Agent: Dalton
   - ID: `019ed8c4-65be-7923-9f9a-2df7f681e952`
   - Scope: `parking_engine/parking_supply.py`

3. Spatiotemporal Weather Integration
   - Agent: Newton
   - ID: `019ed8c4-66bb-7631-b09c-c0395c8576ca`
   - Scope: `parking_engine/weather_context.py`

4. Event Calendar Injection
   - Agent: Ohm
   - ID: `019ed8c4-6777-7702-ae47-b03a5bafe997`
   - Scope: `parking_engine/event_context.py`

5. RegressorChain Architecture
   - Agent: Herschel
   - ID: `019ed8c4-68da-7672-8210-c8e234f5aca4`
   - Scope: `parking_engine/modeling.py`

6. SHAP Values Explainability API
   - Agent: Heisenberg
   - ID: `019ed8c4-6983-7061-ae4d-a70a17e594e9`
   - Scope: `parking_engine/explainability.py`, `frontend/src/app/api/explain/...`

## Queued Due To Agent Thread Limit

7. Feedback Loop / Enforcement Outcome Logging
   - Planned scope: `parking_engine/feedback_store.py`, `frontend/src/app/api/feedback/route.ts`, `frontend/src/components/DispatchQueue.tsx`

8. Validation Dashboard
   - Planned scope: `parking_engine/validation.py`, `frontend/src/app/api/validation/route.ts`, `frontend/src/app/validation/page.tsx`

## Integration Notes

- The first four data-engineering workers are intentionally creating standalone modules. The main integration pass will wire their outputs into `features.py`, `config.py`, and `train.py` after the modules land.
- Feedback and validation workers will be launched as soon as an agent slot is free.
