"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

export default function TodayPage() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.today().then(setData).catch((e) => setErr(e.message));
  }, []);

  const request = data?.open_request;
  const draft = data?.draft_consent;
  const lastAuto = data?.last_auto;
  const farmName = data?.farm?.display_name ?? "Riverside Farms";

  return (
    <>
      <h1>Today</h1>
      {err && <p className="bad">{err} — is the API running on :8000?</p>}

      {lastAuto && (
        <section className="card">
          <h2>Origin already sent it</h2>
          <p>
            Standing permission covered this request. The elevator got the spray statement — not your yield.
            Revoke on Who if that was wrong.
          </p>
          <p className="muted">{lastAuto.reason}</p>
        </section>
      )}

      {request && (
        <section className="card">
          <h2>{request.partner_name} wants a spray statement</h2>
          <p>They asked for this season’s spray facts for the elevator file. Record the field once. You decide who sees it.</p>
          <BigButton onClick={() => router.push("/capture")}>Record what I did</BigButton>
        </section>
      )}

      {draft && (
        <section className="card">
          <h2>Review before they see anything</h2>
          <p>{draft.partner_name} is waiting on your yes or no. Origin will not send this on its own.</p>
          <BigButton onClick={() => router.push(`/consent/${draft.id}`)}>Open consent</BigButton>
        </section>
      )}

      {!request && !draft && !lastAuto && (
        <section className="card">
          <h2>Record what you just did</h2>
          <p className="muted">{farmName}</p>
          <BigButton onClick={() => router.push("/capture")}>Speak or snap</BigButton>
        </section>
      )}
    </>
  );
}
