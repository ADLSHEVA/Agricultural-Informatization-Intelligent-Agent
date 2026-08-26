// The public hackathon deployment uses an isolated seeded tenant. Production
// deployments set Firebase ID tokens at sign-in instead of shipping demo data.
const demo = process.env.NEXT_PUBLIC_DEMO_MODE !== "false";
export const FARMER_TOKEN = process.env.NEXT_PUBLIC_FARMER_TOKEN ?? (demo ? "demo-farmer" : "");
export const PARTNER_TOKEN = process.env.NEXT_PUBLIC_PARTNER_TOKEN ?? (demo ? "demo-partner" : "");

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
}
