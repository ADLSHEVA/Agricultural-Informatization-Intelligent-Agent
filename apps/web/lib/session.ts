export const FARMER_TOKEN = "demo-farmer";
export const PARTNER_TOKEN = "demo-partner";

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
}
