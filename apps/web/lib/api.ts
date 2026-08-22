import { apiBase, FARMER_TOKEN, PARTNER_TOKEN } from "./session";

async function req(path: string, init: RequestInit = {}, token = FARMER_TOKEN) {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${apiBase()}${path}`, { ...init, headers });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.detail ?? data ?? { code: "error", message: res.statusText };
    const message = typeof err === "string" ? err : err.message || res.statusText;
    throw Object.assign(new Error(message || "Request failed"), { status: res.status, body: err });
  }
  return data;
}

export type RuleDraft = {
  id: string;
  farm_id: string;
  partner_id: string;
  partner_name: string;
  market: string;
  source_excerpt: string;
  pack: {
    id: string;
    fields: string[];
    purpose: string;
    until: string;
    reuse: boolean;
    exclude?: string[];
  };
  dropped_refused: string[];
  dropped_unknown: string[];
  refused_fields: string[];
  unknown_fields: string[];
  plain_summary: string;
  state: "proposed" | "approved" | "rejected";
  created_at: string;
  decided_at: string | null;
};

export type TermsReview = {
  id: string;
  farm_id: string;
  partner_name: string;
  locale: string;
  source_excerpt: string;
  resale: "yes" | "no" | "unclear" | string;
  aggregation: "yes" | "no" | "unclear" | string;
  third_parties: string[];
  retention_days: number | null;
  fields_claimed: string[];
  red_flags: string[];
  over_ask: string[];
  plain_summary: string;
  created_at: string;
};

export const api = {
  today: () => req("/v1/today"),
  postEvent: (form: FormData) => req("/v1/events", { method: "POST", body: form }),
  confirmEvent: (id: string, body: Record<string, unknown>) =>
    req(`/v1/events/${id}/confirm`, { method: "POST", body: JSON.stringify(body) }),
  getConsent: (id: string) => req(`/v1/consents/${id}`),
  bind: (id: string, body: { standing?: boolean } = {}) =>
    req(`/v1/consents/${id}/bind`, { method: "POST", body: JSON.stringify(body) }),
  refuse: (id: string) => req(`/v1/consents/${id}/refuse`, { method: "POST" }),
  revoke: (id: string) => req(`/v1/consents/${id}/revoke`, { method: "POST" }),
  receipts: () => req("/v1/receipts"),
  exportMe: () => req("/v1/me/export"),
  eraseMe: () => req("/v1/me", { method: "DELETE" }),
  deskPacks: () => req("/v1/desk/packs", {}, PARTNER_TOKEN),
  deskRequest: (farmId = "demo-farm") =>
    req("/v1/desk/requests", { method: "POST", body: JSON.stringify({ farm_id: farmId }) }, PARTNER_TOKEN),
  deskQuestionnaire: (form: FormData) =>
    req("/v1/desk/questionnaires", { method: "POST", body: form }, PARTNER_TOKEN) as Promise<RuleDraft>,
  ruleDrafts: () => req("/v1/rule-drafts") as Promise<RuleDraft[]>,
  approveRuleDraft: (id: string) =>
    req(`/v1/rule-drafts/${id}/approve`, { method: "POST" }) as Promise<RuleDraft>,
  rejectRuleDraft: (id: string) =>
    req(`/v1/rule-drafts/${id}/reject`, { method: "POST" }) as Promise<RuleDraft>,
  reviewTerms: (body: { text: string; partner_name?: string }) =>
    req("/v1/terms/review", { method: "POST", body: JSON.stringify(body) }) as Promise<TermsReview>,
};
