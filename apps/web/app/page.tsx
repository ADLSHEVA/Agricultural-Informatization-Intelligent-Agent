"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type AgentRun, type RuleDraft } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

function ShieldGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3 20 6v5c0 5.2-3.2 8.3-8 10-4.8-1.7-8-4.8-8-10V6l8-3Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="m8.5 12 2.2 2.2 4.8-5" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function RunTimeline({ run }: { run: AgentRun }) {
  return (
    <article className="run-entry">
      <div className="run-head">
        <div>
          <strong>{run.decision ? run.decision.replace(/_/g, " ") : "Checking request"}</strong>
          <p className="trace-label">Trace {run.trace_id}</p>
        </div>
        <span className={`status status-${run.status}`}>{run.status.replace(/_/g, " ")}</span>
      </div>
      <ol className="timeline">
        {(run.steps ?? []).map((step, index) => (
          <li key={`${step.name}-${index}`}>
            <strong>{step.name.replace(/_/g, " ")}</strong>
            <span>{step.detail}</span>
          </li>
        ))}
      </ol>
      {run.model?.provider && (
        <p className="model-line">
          {run.model.provider}
          {run.model.model && run.model.model !== "none" ? ` · ${run.model.model}` : ""}
          {run.model.location ? ` · ${run.model.location}` : ""}
        </p>
      )}
      {run.error && <p className="bad">{run.error}</p>}
    </article>
  );
}

export default function TodayPage() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [drafts, setDrafts] = useState<RuleDraft[]>([]);
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  function load() {
    Promise.all([api.today(), api.ruleDrafts()])
      .then(([today, rows]) => {
        setData(today);
        setDrafts((rows || []).filter((d) => d.state === "proposed"));
      })
      .catch((e) => setErr(e.message));
  }

  useEffect(() => {
    setJustSaved(new URLSearchParams(window.location.search).has("saved"));
    load();
  }, []);

  async function decideDraft(id: string, approve: boolean) {
    setBusyId(id);
    try {
      if (approve) await api.approveRuleDraft(id);
      else await api.rejectRuleDraft(id);
      load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusyId("");
    }
  }

  const requests: any[] = data?.open_requests ?? (data?.open_request ? [data.open_request] : []);
  const consentDrafts: any[] = data?.draft_consents ?? (data?.draft_consent ? [data.draft_consent] : []);
  const lastAuto = data?.last_auto;
  const lastDecision = data?.last_decision;
  const farmName = data?.farm?.display_name ?? "Riverside Farms";
  const runs: AgentRun[] = data?.agent_runs ?? [];
  const policies = data?.standing_policies?.length ?? 0;
  const pending = drafts.length + requests.length + consentDrafts.length;
  const latestRun = runs[0];
  const loading = !data && !err;

  return (
    <>
      <section className="dashboard-intro">
        <div>
          <p className="eyebrow">{farmName} · 2026 crop year</p>
          <h1>Your farm data, on your terms.</h1>
          <p className="intro-copy">
            Record field work once. Origin handles routine partner requests only inside the boundary you set.
          </p>
        </div>
        <div className="control-promise">
          <span className="promise-icon"><ShieldGlyph /></span>
          <span>
            <strong>You stay in control</strong>
            <small>Gemini reads. Your rules decide. Every action leaves a receipt.</small>
          </span>
        </div>
      </section>

      {err && (
        <div className="alert alert-error" role="alert">
          <strong>Origin could not reach the farm service.</strong>
          <span>{err}. Your typed notes remain on this device.</span>
        </div>
      )}

      <section className="signal-grid" aria-label="Farm data status">
        <div className="signal">
          <span className={`signal-dot ${pending ? "attention" : "safe"}`} aria-hidden="true" />
          <span><small>Needs you</small><strong>{loading ? "Checking…" : pending ? `${pending} decision${pending === 1 ? "" : "s"}` : "Nothing pending"}</strong></span>
        </div>
        <div className="signal">
          <span className="signal-number">{policies}</span>
          <span><small>Standing permissions</small><strong>{policies ? "Bounded automation on" : "Manual approval only"}</strong></span>
        </div>
        <div className="signal">
          <span className={`signal-dot ${latestRun?.status === "failed" ? "blocked" : "live"}`} aria-hidden="true" />
          <span><small>Latest agent run</small><strong>{latestRun ? latestRun.status.replace(/_/g, " ") : "Ready"}</strong></span>
        </div>
      </section>

      <div className="dashboard-layout">
        <section className="task-stack" aria-labelledby="today-action">
          <div className="section-title">
            <div>
              <p className="eyebrow">Today</p>
              <h2 id="today-action">What needs attention</h2>
            </div>
            <button className="text-action" type="button" onClick={load}>Refresh</button>
          </div>

          {loading && (
            <section className="card task-card skeleton-card" aria-label="Loading today's work">
              <span className="skeleton-line wide" />
              <span className="skeleton-line" />
              <span className="skeleton-block" />
            </section>
          )}

          {justSaved && (
            <section className="card task-card task-success">
              <div className="task-copy">
                <span className="task-label">Saved to your farm</span>
                <h2>Field record saved. Nothing was shared.</h2>
                <p>There is no open partner request. Origin will re-check the recipient, purpose, and fields if one arrives later.</p>
              </div>
              <BigButton kind="ghost" onClick={() => router.push("/capture")}>Record another job</BigButton>
            </section>
          )}

          {drafts.map((d) => (
            <section key={d.id} className="card task-card task-attention">
              <div className="task-copy">
                <span className="task-label">New sharing rule · approval required</span>
                <h2>{d.partner_name} sent a new questionnaire</h2>
                <p>{d.plain_summary}</p>
                {d.until_date && <p className="supporting">Requested through {d.until_date}.</p>}
                {d.refused_fields?.length || d.dropped_refused?.length ? (
                  <p className="exclusion-note">
                    <ShieldGlyph /> Origin removed {(d.refused_fields || d.dropped_refused).join(", ")} before this reached you.
                  </p>
                ) : null}
              </div>
              <div className="row">
                <BigButton disabled={!!busyId} onClick={() => decideDraft(d.id, true)}>Approve rule</BigButton>
                <BigButton kind="ghost" disabled={!!busyId} onClick={() => decideDraft(d.id, false)}>Decline</BigButton>
              </div>
            </section>
          ))}

          {lastAuto && (
            <section className="card task-card task-success">
              <div className="task-copy">
                <span className="task-label">Handled within your permission</span>
                <h2>Origin completed the repeat request</h2>
                <p>{lastAuto.note ?? "Standing permission covered this spray statement. No extra farm data was included."}</p>
                <p className="supporting">{lastAuto.reason}</p>
              </div>
              <BigButton kind="ghost" onClick={() => router.push("/receipts")}>See sharing receipt</BigButton>
            </section>
          )}

          {requests.map((request) => {
            const purpose = String(request.purpose || "farm data statement").replace(/_/g, " ");
            return <section key={request.id} className="card task-card task-primary">
              <div className="task-copy">
                <span className="task-label">Field record needed</span>
                <h2>{request.partner_name} needs a {purpose}</h2>
                <p>Record the work for {request.parcel_id || "the requested field"}. You will review the extracted facts and exactly what the elevator can receive.</p>
                <div className="request-meta">
                  <span>Purpose: {purpose}</span>
                  <span>Yield excluded</span>
                  <span>Revenue excluded</span>
                </div>
              </div>
              <BigButton onClick={() => router.push(`/capture?parcel=${encodeURIComponent(request.parcel_id || "p3")}`)}>Record field work</BigButton>
            </section>;
          })}

          {consentDrafts.map((draft) => {
            const askNote = lastDecision?.decision === "ask_farmer" && lastDecision?.consent_id === draft.id ? lastDecision : null;
            const overAsk: string[] = askNote?.extra_fields ?? [];
            return <section key={draft.id} className="card task-card task-attention">
              <div className="task-copy">
                <span className="task-label">Your approval is required</span>
                <h2>Review before {draft.partner_name} sees anything</h2>
                <p>{askNote?.note ?? "Origin has prepared the smallest matching data pack. It will not leave your farm until you decide."}</p>
                {overAsk.length > 0 && (
                  <p className="exclusion-note"><ShieldGlyph /> New request blocked: {overAsk.join(", ")} is outside your permission.</p>
                )}
              </div>
              <BigButton onClick={() => router.push(`/consent/${draft.id}`)}>Review exact data</BigButton>
            </section>;
          })}

          {requests.length === 0 && consentDrafts.length === 0 && !lastAuto && drafts.length === 0 && !justSaved && !loading && (
            <section className="card task-card task-calm">
              <div className="task-copy">
                <span className="task-label">No partner is waiting</span>
                <h2>Capture the work while it is fresh</h2>
                <p>A quick voice note or photo is enough. Saving a field record never gives anyone permission to receive it.</p>
              </div>
              <BigButton onClick={() => router.push("/capture")}>Record field work</BigButton>
            </section>
          )}
        </section>

        <aside className="agent-console" aria-labelledby="agent-activity">
          <div className="console-head">
            <div>
              <p className="eyebrow">Live audit trail</p>
              <h2 id="agent-activity">Agent activity</h2>
            </div>
            <span className="agent-live"><span /> {runs.some((r) => r.status === "running" || r.status === "queued") ? "Working" : "Ready"}</span>
          </div>
          <p className="console-intro">See the policy checks and tool actions behind every decision.</p>
          {runs.length ? runs.slice(0, 2).map((run) => <RunTimeline run={run} key={run.id} />) : (
            <div className="empty-trace">
              <ShieldGlyph />
              <strong>No hidden actions</strong>
              <span>The next request will show its checks here, step by step.</span>
            </div>
          )}
          {runs.length > 2 && <p className="trace-count">{runs.length - 2} earlier runs are kept in the audit log.</p>}
        </aside>
      </div>

      <section className="boundary-strip" aria-label="Origin authority boundary">
        <div><span>01</span><strong>Gemini reads</strong><p>Voice, photos, forms, and terms become a draft you can correct.</p></div>
        <div><span>02</span><strong>Rules decide</strong><p>Recipient, purpose, exact fields, and expiry are checked deterministically.</p></div>
        <div><span>03</span><strong>Origin acts</strong><p>Only a matching request is delivered, with a trace and receipt.</p></div>
      </section>
    </>
  );
}
