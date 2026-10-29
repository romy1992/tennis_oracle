import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AccountCredentialsPanel } from "./AccountCredentialsPanel";

const updateCredentials = vi.fn();

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ username: "admin", updateCredentials })
}));

describe("AccountCredentialsPanel", () => {
  it("rejects mismatching passwords without calling the API", async () => {
    render(<AccountCredentialsPanel />);
    fireEvent.change(screen.getByLabelText("Nuova password"), { target: { value: "nuova-password" } });
    fireEvent.change(screen.getByLabelText("Conferma nuova password"), { target: { value: "diversa-123" } });
    fireEvent.change(screen.getByLabelText("Password attuale"), { target: { value: "vecchia" } });
    fireEvent.click(screen.getByRole("button", { name: "Aggiorna credenziali" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("non coincidono");
    expect(updateCredentials).not.toHaveBeenCalled();
  });

  it("sends only the changed fields", async () => {
    updateCredentials.mockResolvedValue(undefined);
    render(<AccountCredentialsPanel />);
    fireEvent.change(screen.getByLabelText("Nuovo username"), { target: { value: "capo" } });
    fireEvent.change(screen.getByLabelText("Password attuale"), { target: { value: "vecchia" } });
    fireEvent.click(screen.getByRole("button", { name: "Aggiorna credenziali" }));
    await waitFor(() => expect(updateCredentials).toHaveBeenCalledWith("vecchia", "capo", undefined));
    expect(await screen.findByRole("status")).toHaveTextContent("Credenziali aggiornate");
  });
});
