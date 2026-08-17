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
    throw Object.assign(new Error(err.message || "Request failed"), { status: res.status, body: err });
  }
  return data;
}

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
};
