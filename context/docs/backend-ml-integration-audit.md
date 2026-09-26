# Backend/ML integration audit

## Current end-to-end path

1. The frontend Analyze action calls `POST /mountains/{slug}/analyze` and follows the run WebSocket.
2. The backend fetches the weather series once, builds the legacy spatial assessment/map, and then
   computes one cell-level production prediction with `app.ml.risk_inference.predict_location`.
3. That serialized prediction is stored on `RunContext.production_prediction` before the analyst
   fan-out begins. Tools return it unchanged to every analyst; no analyst performs a second model or
   weather fetch in the production path.
4. The synthesizer uses the calibrated classifier's `risk_level` only when the shared contract says
   the prediction is decision-eligible. It can never authorize `close` from the legacy map alone.
5. The advisory and run snapshot expose the classifier state, calibrated probability, threshold,
   eligibility, and reason codes. The frontend renders that status next to the streamed agent result.
6. The old client-side scripted orchestrator and synthetic demo traces were removed. The frontend
   now has one Analyze path: backend run, WebSocket events, advisory, and model status.

## What remains intentionally separate

The legacy Model B/terrain map still renders tiles and ranks trail segments. It is useful spatial
context, but it is not a calibrated probability of a landslide in the next 72 hours. It is never
promoted to `HIGH_RISK` or `NOT_HIGH_RISK` by the new integration gate.

At the time of this audit, the repository does not contain the strict artifacts
`ml/artifacts/landslide_risk_lgbm.txt`, `risk_model.json`, and `risk_calibration.json`. Therefore a
normal local run correctly returns `UNCERTAIN`, carries the missing/stale-data reason codes, keeps
the legacy map available for visualization, and requires review. This is a safe deployment state,
not evidence that the classifier has passed validation.

## Leakage and duplicate-work protections

- The run coordinator fetches rain before model inference and passes the same object to the map,
  classifier, and agents.
- Agent tools reuse `RunContext.production_prediction`; the fallback only exists for direct CLI/test
  contexts and uses an already supplied rain object.
- No post-reference timestamp is introduced by the integration layer.
- `production_decision_eligible` requires a calibrated source, a binary production state, a threshold,
  a risk level, and a calibrated probability. Relative map estimates fail this check.
- Missing forecasts, static data, calibration, or domain coverage remain `UNCERTAIN`; they are not
  silently imputed into `NOT_HIGH_RISK`.

## Validation performed

The backend suite and focused cache/decision-gate tests pass. Frontend typecheck and lint pass with
the repository's existing warnings. The remaining deployment prerequisite is to build and validate
the strict risk artifacts from event-time historical forecast data; until then, the production run
must remain advisory.
