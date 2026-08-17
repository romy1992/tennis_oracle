import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ModelControls } from "./ModelControls";

describe("ModelControls", () => {
  it("shows market and model selectors and notifies changes", async () => {
    const onModelVersionChange = vi.fn();
    const onModelNameChange = vi.fn();
    const user = userEvent.setup();

    render(
      <ModelControls
        modelVersion="v4"
        modelName="logistic_regression"
        onModelVersionChange={onModelVersionChange}
        onModelNameChange={onModelNameChange}
      />
    );

    expect(screen.getByText("Mercato")).toBeInTheDocument();
    expect(screen.getByText("Modello")).toBeInTheDocument();

    const marketSelect = screen.getByLabelText("Mercato");
    const modelSelect = screen.getByLabelText("Modello");
    expect(marketSelect).toHaveValue("v4");
    expect(modelSelect).toHaveValue("logistic_regression");

    await user.selectOptions(modelSelect, "random_forest");
    expect(onModelNameChange).toHaveBeenCalledWith("random_forest");
    expect(localStorage.getItem("tennis_oracle_selected_model_name")).toBe("random_forest");
  });
});
