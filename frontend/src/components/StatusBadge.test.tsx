import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it.each([
    ["done", "Ready"],
    ["needs_review", "Needs review"],
    ["processing", "Processing"],
    ["failed", "Failed"],
    ["something-new", "Queued"],
  ])("%s reads %s", (status, label) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
