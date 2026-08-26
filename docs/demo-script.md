# Origin demo script

Target length: **3:20**. Record the deployed Cloud Run application in a desktop browser. Keep the Partner Desk in a second tab.

## 0:00–0:25 — Problem and promise

Show the Today page.

> Farmers keep re-entering the same field facts into partner portals. Origin is a bounded AI agent that captures a fact once, then handles repeat requests only inside permission the farmer explicitly drew.

Point to the partner request and the agent activity card.

## 0:25–1:05 — Multimodal capture

Open Speak, select Ditch 40, and type or say:

> Sprayed Field 3 today with GreenGuard at 1.2 liters per hectare and kept a 5 meter buffer by the ditch.

Submit, then show the draft's confidence, Gemini model/location, and fallback indicator. Confirm the draft.

> Gemini turns messy evidence into a structured draft. The farmer remains the source of truth. Geometry and field minimization are deterministic tools, not model judgments.

## 1:05–1:40 — Exact consent and first external action

On the consent card, slowly show recipient, purpose, expiry, and the exact field/value table. Check standing permission, then Give.

Switch to Partner Desk and open the current package.

> Origin delivered a recipient-specific JSON package and recorded its trace. Every partner request is a durable AgentRun, so an action can queue, retry, pause, and resume without losing its audit history.

## 1:40–2:20 — Real agent behavior

Return to Speak and quickly save a second confirmed operation on South 40. Show the message that no open request exists, so nothing was sent. Then click **Ask the farm again** on Partner Desk and wait for the run to complete. Show the run timeline and new delivery destination.

> Capturing a fact alone is never permission to publish it. When the new request arrives, Cloud Tasks runs it in the background. The deterministic gate sees the same partner, purpose, fields, and valid expiry, so the agent delivers the new fact automatically and tells the farmer what it did.

Click **Boundary test: change purpose** and show `waiting_for_farmer`.

> The fields are familiar, but the purpose changed. That leaves the permission boundary, so the agent stops and asks. Gemini can read and explain; it can never authorize the share.

## 2:20–2:55 — Revocation and honest deletion

Open Who, show the grouped receipt, then revoke.

> Revocation disables Origin-issued access immediately and records a recipient notice. Origin does not make the dishonest claim that it can erase a file a recipient already downloaded.

Show the erase wording without erasing the seeded demo unless a reset is available.

## 2:55–3:20 — Architecture and close

Show `docs/architecture.png` or place it as a final video slide.

> The web and API run on Cloud Run; Cloud Tasks drives durable AgentRuns; Firestore stores state; Cloud Storage holds evidence and deliveries; and Gemini runs on Vertex AI. Origin turns AI automation into accountable delegation: capture once, share only on your terms, and see every action.

## Recording checklist

- Confirm the deployed API health response reports `firestore`, `tasks`, and the Vertex model.
- Pre-warm both Cloud Run services before recording.
- Use a fresh seeded data prefix or reset state before each take.
- Keep browser zoom at 100% and hide bookmarks or private account details.
- Show the URL briefly as proof of a Cloud Run deployment.
- Keep the final video below four minutes.
