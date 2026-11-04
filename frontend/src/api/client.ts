import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/** The owner whose data every request reads and writes (sent as X-Owner-Id). */
let currentOwner = "demo";
export function setApiOwner(owner: string) {
  currentOwner = owner;
}
export function apiOwner() {
  return currentOwner;
}

export const api = createClient<paths>({ baseUrl: "/api" });
api.use({
  onRequest({ request }) {
    request.headers.set("X-Owner-Id", currentOwner);
    return request;
  },
});

export type DocumentSummary = components["schemas"]["DocumentSummary"];
export type DocumentDetail = components["schemas"]["DocumentDetail"];
export type Discrepancy = components["schemas"]["DiscrepancyOut"];
export type UploadResult = components["schemas"]["UploadResult"];
export type AskOut = components["schemas"]["AskOut"];

export class ApiError extends Error {}

/** Uploads go through fetch directly: multipart bodies are simplest without the typed client. */
export async function uploadDocument(file: File): Promise<{ result: UploadResult; duplicate: boolean }> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/documents", {
    method: "POST",
    headers: { "X-Owner-Id": currentOwner },
    body,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(detail?.detail ?? `Upload failed (${response.status})`);
  }
  return { result: (await response.json()) as UploadResult, duplicate: response.status === 200 };
}
