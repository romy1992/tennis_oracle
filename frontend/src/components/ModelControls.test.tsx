import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ModelControls } from "./ModelControls";

describe("ModelControls", () => {
  it("shows version and model selectors and notifies changes", async () => {
    const onModelVersionChange = vi.fn();
    const onModelNameChange = vi.fn();
    const user = userEvent.setup();

    render(
      <ModelControls
        modelVersion="v3"
        modelName="logistic_regression"
        onModelVersionChange={onModelVersionChange}
        onModelNameChange={onModelNameChange}
      />
    );

    expect(screen.getByText("Versione modello")).toBeInTheDocument();
    expect(screen.getByText("Modello")).toBeInTheDocument();

    const versionSelect = screen.getByLabelText("Versione modello");
    const modelSelect = screen.getByLabelText("Modello");
    expect(versionSelect).toHaveValue("v3");
    expect(modelSelect).toHaveValue("logistic_regression");

    await user.selectOptions(versionSelect, "v2");
    expect(onModelVersionChange).toHaveBeenCalledWith("v2");
    expect(localStorage.getItem("tennis_oracle_selected_model_version")).toBe("v2");

    await user.selectOptions(modelSelect, "random_forest");
    expect(onModelNameChange).toHaveBeenCalledWith("random_forest");
    expect(localStorage.getItem("tennis_oracle_selected_model_name")).toBe("random_forest");
  });
});
