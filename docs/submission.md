# Hackathon submission checklist

## Positioning

**One-line pitch**

Origin is a farmer-controlled AI agent that turns voice or photo evidence into the smallest safe partner data share, then autonomously fulfills only repeat requests inside an explicit consent boundary.

**Primary use case**

Taskmaster: a durable, asynchronous request-to-action workflow with tool use, external delivery, retry safety, and a human checkpoint.

**What is new**

Most consent products ask once and most agents act broadly. Origin converts consent into an executable, field-level boundary: same recipient, same purpose, requested fields contained in allowed fields, and a valid expiry. It automates the boring repeats while routing changed requests back to the person whose data is at stake.

## Suggested project description

Farmers repeatedly enter the same field records into elevator, retailer, and certification portals. Origin captures a fact once from voice, photo, or text, has the farmer confirm Gemini's structured draft, and compiles only the fields a partner requested for that parcel. Each new request becomes a durable AgentRun dispatched by Cloud Tasks; equivalent open requests reuse it. A deterministic policy gate—not the model—checks recipient, purpose, exact field containment, and expiry. Covered repeats are delivered idempotently to Cloud Storage or a signed webhook; anything new pauses for a field/value-level consent decision. Firestore holds the run timeline, permissions, receipts, and provenance, Cloud Run hosts the FastAPI agent, and Render serves the responsive Next.js experience. Farmers can see what happened, revoke Origin-issued access, and export their data. Private tenants can erase Origin-managed copies after recipient notices; the public shared judge tenant blocks destructive erasure. Origin shows how agentic automation can remain useful, observable, and accountable in a high-trust domain.

## Required assets

- [x] Public source repository with an open-source license
- [x] English README with setup and testing instructions
- [x] Google Cloud architecture diagram
- [x] Under-four-minute demo script
- [x] Gemini and Google Cloud integration identified in code and documentation
- [x] Durable `AgentRun` and external action visible in the product
- [x] Public deployed application URL
- [ ] Public or unlisted demo video URL
- [ ] Devpost team and member details
- [ ] Final Devpost category/bonus selections

## Proof to capture after deployment

| Proof | Value to insert |
|---|---|
| Web URL | `https://origin-farm-agent.onrender.com` |
| API health URL | `https://origin-api-n4v5i2jtda-ew.a.run.app/health` |
| Cloud Run region | `europe-west1` |
| Cloud Tasks queue | `origin-agent` |
| Firestore database | `(default)` |
| Storage bucket | project-specific, not public |
| Vertex model | `gemini-3.7-flash` by default |
| Commit used for video | `TBD` |

Do not publish the internal worker token, Firebase credentials, service-account material, webhook secret, private bucket objects, or personal Cloud Console screenshots.

## Final verification

```powershell
Set-Location apps\api
$env:PYTHONPATH = "."
py -3 -m pytest tests -q

Set-Location ..\web
npx tsc --noEmit
npm run build

Set-Location ..\..
git diff --check
git status --short
git ls-files
```

Verify that tracked filenames and tracked text contain no Chinese characters before pushing the submission commit. Local Chinese planning notes remain ignored by `.gitignore`.
