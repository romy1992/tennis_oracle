import { describe, expect, it } from "vitest";
import { classifySingleBetValue } from "./minEdge";

describe("classifySingleBetValue", () => {
  it("returns PLAY when market odds clear the edge threshold", () => {
    expect(classifySingleBetValue(2.2, 2.0, 5)).toBe("PLAY");
  });

  it("returns NO BET when market odds are below void odds", () => {
    expect(classifySingleBetValue(1.8, 2.0, 5)).toBe("NO BET");
  });

  it("returns BORDERLINE between void odds and play threshold", () => {
    expect(classifySingleBetValue(2.05, 2.0, 5)).toBe("BORDERLINE");
  });
});
