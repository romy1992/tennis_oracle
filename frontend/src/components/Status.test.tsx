import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";

describe("Status components", () => {
  it("renders loading state", () => {
    render(<LoadingState title="Caricamento partite..." />);
    expect(screen.getByText("Caricamento partite...")).toBeInTheDocument();
  });

  it("renders error state with message", () => {
    render(<ErrorState title="Partite non disponibili" message="boom" />);
    expect(screen.getByText("Partite non disponibili")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(<EmptyState title="Nessuna partita" message="Niente da mostrare" />);
    expect(screen.getByText("Nessuna partita")).toBeInTheDocument();
    expect(screen.getByText("Niente da mostrare")).toBeInTheDocument();
  });
});
