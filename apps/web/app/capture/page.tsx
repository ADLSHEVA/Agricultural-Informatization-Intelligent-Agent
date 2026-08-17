"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { BigButton } from "@/components/BigButton";

type Draft = {
  id: string;
  parcel_id: string;
  product_name: string;
  rate: number | null;
  unit: string;
  buffer_m: number | null;
  note: string;
  confidence: number;
};

export default function CapturePage() {
  const router = useRouter();
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const [holding, setHolding] = useState(false);
  const [audio, setAudio] = useState<Blob | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [note, setNote] = useState("Field 3, product X, 1.2 L/ha, 16 ft filter strip by the ditch");
  const [parcel, setParcel] = useState("p3");
  const [parcels, setParcels] = useState<any[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.today().then((t) => {
      if (t.parcels?.length) setParcels(t.parcels);
    }).catch(() => undefined);
  }, []);

  async function startHold() {
    setErr("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = [];
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setAudio(new Blob(chunks.current, { type: mr.mimeType || "audio/webm" }));
      };
      rec.current = mr;
      mr.start();
      setHolding(true);
    } catch {
      setErr("Mic blocked — type the three facts below instead.");
    }
  }

  function stopHold() {
    rec.current?.stop();
    setHolding(false);
  }

  async function send() {
    setBusy(true);
    setErr("");
    try {
      const form = new FormData();
      form.set("parcel_id", parcel);
      form.set("note", note);
      if (audio) form.set("audio", audio, "voice.webm");
      if (image) form.set("image", image);
      const ev = await api.postEvent(form);
      setDraft(ev);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!draft) return;
    setBusy(true);
    try {
      const res = await api.confirmEvent(draft.id, {
        product_name: draft.product_name,
        rate: draft.rate,
        unit: draft.unit,
        buffer_m: draft.buffer_m,
        note: draft.note,
        parcel_id: draft.parcel_id,
      });
      router.push(res.auto ? "/receipts" : `/consent/${res.consent.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (draft) {
    return (
      <>
        <h1>Is this right?</h1>
        <section className="card">
          <label>Parcel</label>
          <select value={draft.parcel_id} onChange={(e) => setDraft({ ...draft, parcel_id: e.target.value })}>
            {parcels.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label} · {p.crop}
              </option>
            ))}
          </select>
          <label>Product</label>
          <input value={draft.product_name} onChange={(e) => setDraft({ ...draft, product_name: e.target.value })} />
          <label>Rate</label>
          <input
            type="number"
            step="0.1"
            value={draft.rate ?? ""}
            onChange={(e) => setDraft({ ...draft, rate: e.target.value ? Number(e.target.value) : null })}
          />
          <label>Buffer (m)</label>
          <input
            type="number"
            step="0.5"
            value={draft.buffer_m ?? ""}
            onChange={(e) => setDraft({ ...draft, buffer_m: e.target.value ? Number(e.target.value) : null })}
          />
          <p className="muted">Fix at most a few words. You are the source of truth.</p>
        </section>
        {err && <p className="bad">{err}</p>}
        <BigButton disabled={busy} onClick={confirm}>
          That’s right
        </BigButton>
      </>
    );
  }

  return (
    <>
      <h1>Speak or snap</h1>
      <section className="card">
        <p>Hold to talk, or photograph the can. One event only.</p>
        <label>Parcel</label>
        <select value={parcel} onChange={(e) => setParcel(e.target.value)}>
          {(parcels.length ? parcels : [{ id: "p3", label: "P3", crop: "wheat" }]).map((p) => (
            <option key={p.id} value={p.id}>
              {p.label} · {p.crop}
            </option>
          ))}
        </select>
        <BigButton
          className={`big hold ${holding ? "rec" : ""}`}
          kind="ghost"
          onMouseDown={startHold}
          onMouseUp={stopHold}
          onTouchStart={(e) => {
            e.preventDefault();
            startHold();
          }}
          onTouchEnd={stopHold}
        >
          {holding ? "Listening…" : audio ? "Recorded — tap send" : "Hold to talk"}
        </BigButton>
        <label>Photo of the can</label>
        <input type="file" accept="image/*" capture="environment" onChange={(e) => setImage(e.target.files?.[0] ?? null)} />
        <label>Or type it</label>
        <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
      </section>
      {err && <p className="bad">{err}</p>}
      <BigButton disabled={busy} onClick={send}>
        {busy ? "Reading…" : "Send"}
      </BigButton>
    </>
  );
}
