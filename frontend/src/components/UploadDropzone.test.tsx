import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UploadDropzone } from "./UploadDropzone";

function renderDropzone() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <UploadDropzone />
    </QueryClientProvider>,
  );
  const input = view.container.querySelector('input[type="file"]') as HTMLInputElement;
  return { input };
}

function respond(status: number, body: object) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

afterEach(() => vi.unstubAllGlobals());

describe("UploadDropzone", () => {
  it("sends the file with the owner header and shows it as queued", async () => {
    const fetchMock = respond(202, { id: "d1", filename: "inv.pdf", status: "queued", job_id: "j1" });
    vi.stubGlobal("fetch", fetchMock);
    const { input } = renderDropzone();

    await userEvent.upload(input, new File(["%PDF-1.4"], "inv.pdf", { type: "application/pdf" }));

    expect(await screen.findByText("Queued for processing")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/documents");
    expect((init.headers as Record<string, string>)["X-Owner-Id"]).toBe("demo");
  });

  it("tells the user when the file was already uploaded", async () => {
    vi.stubGlobal("fetch", respond(200, { id: "d1", filename: "inv.pdf", status: "done", job_id: null }));
    const { input } = renderDropzone();
    await userEvent.upload(input, new File(["%PDF-1.4"], "inv.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Already uploaded")).toBeInTheDocument();
  });

  it("shows the server's reason when an upload is rejected", async () => {
    vi.stubGlobal("fetch", respond(415, { detail: "only PDF files are accepted" }));
    const { input } = renderDropzone();
    await userEvent.upload(input, new File(["x"], "notes.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(screen.getByText("only PDF files are accepted")).toBeInTheDocument());
  });
});
