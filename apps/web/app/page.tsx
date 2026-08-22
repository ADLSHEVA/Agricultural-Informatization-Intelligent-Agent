"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type RuleDraft } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

export default function TodayPage() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [drafts, setDrafts] = useState<RuleDraft[]>([]);
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState("");

  function load() {
    Promise.all([api.today(), api.ruleDrafts()])
      .then(([today, rows]) => {
        setData(today);
        setDrafts((rows || []).filter((d) => d.state === "proposed"));
      })
      .catch((e) => setErr(e.message));
  }

  useEffect(load, []);

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

  const request = data?.open_request;
  const draft = data?.draft_consent;
  const lastAuto = data?.last_auto;
  const lastDecision = data?.last_decision;
  const farmName = data?.farm?.display_name ?? "Riverside Farms";

  // The agent narrates in the farmer's own language, so prefer its note over
  // any English written into this file. Falls back when Vertex is unreachable.
  const askNote =
    lastDecision?.decision === "ask_farmer" && lastDecision?.consent_id === draft?.id
      ? lastDecision
      : null;
  const overAsk: string[] = askNote?.extra_fields ?? [];

  return (
    <>
      <div className="page-head">
        <h1>Today</h1>
        {err && <p className="bad">{err} — is the API running on :8000?</p>}
      </div>

      <div className="card-grid">
        {drafts.map((d) => (
          <section key={d.id} className="card card-hero">
            <div>
              <h2>{d.partner_name} wants a new share pack</h2>
              <p>{d.plain_summary}</p>
              {d.refused_fields?.length || d.dropped_refused?.length ? (
                <p className="bad">
                  They asked for {(d.refused_fields || d.dropped_refused).join(", ")}. Origin stripped that.
                </p>
              ) : null}
            </div>
            <div className="row">
              <BigButton disabled={!!busyId} onClick={() => decideDraft(d.id, true)}>
                Approve
              </BigButton>
              <BigButton kind="danger" disabled={!!busyId} onClick={() => decideDraft(d.id, false)}>
                Refuse
              </BigButton>
            </div>
          </section>
        ))}

        {lastAuto && (
          <section className="card card-hero">
            <div>
              <h2>Origin already sent it</h2>
              <p>
                {lastAuto.note ??
                  "Standing permission covered this request. The elevator got the spray statement — not your yield."}
              </p>
              <p className="muted">Revoke on Who if that was wrong. {lastAuto.reason}</p>
            </div>
            <BigButton kind="ghost" onClick={() => router.push("/receipts")}>
              Open Who
            </BigButton>
          </section>
        )}

        {request && (
          <section className="card card-hero">
            <div>
              <h2>{request.partner_name} wants a spray statement</h2>
              <p>
                They asked for this season’s spray facts for the elevator file. Record the field once. You
                decide who sees it.
              </p>
            </div>
            <BigButton onClick={() => router.push("/capture")}>Record what I did</BigButton>
          </section>
        )}

        {draft && (
          <section className="card card-hero">
            <div>
              <h2>Review before they see anything</h2>
              <p>
                {askNote?.note ??
                  `${draft.partner_name} is waiting on your yes or no. Origin will not send this on its own.`}
              </p>
              {overAsk.length > 0 && (
                <p className="bad">
                  They now also want {overAsk.join(", ")} — never in your box, so Origin sent nothing.
                </p>
              )}
            </div>
            <BigButton onClick={() => router.push(`/consent/${draft.id}`)}>Open consent</BigButton>
          </section>
        )}

        {!request && !draft && !lastAuto && drafts.length === 0 && (
          <section className="card card-hero">
            <div>
              <h2>Record what you just did</h2>
              <p className="muted">{farmName}</p>
            </div>
            <BigButton onClick={() => router.push("/capture")}>Speak or snap</BigButton>
          </section>
        )}
      </div>
    </>
  );
}
