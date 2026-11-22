import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { excludedPartiesFor, ExcludedPartiesNotice } from "./ExcludedPartiesNotice";

describe("excludedPartiesFor", () => {
  test("names EAJ-PNV and Frente Obrero for the 2026 general election", () => {
    const notes = excludedPartiesFor({ type: "general", date: "2026-11-29" });
    expect(notes).toHaveLength(1);
    expect(notes[0]).toContain("EAJ-PNV");
    expect(notes[0]).toContain("Frente Obrero");
    expect(notes[0]).toContain("no se incluyen en los resultados");
  });

  test("is empty for any other Election", () => {
    expect(excludedPartiesFor({ type: "general", date: "2023-07-23" })).toEqual([]);
  });
});

describe("ExcludedPartiesNotice", () => {
  test("renders a titled note with each explanation", () => {
    render(<ExcludedPartiesNotice notes={["Nota A."]} />);
    const note = screen.getByRole("note", { name: "Partidos no incluidos en el cálculo" });
    expect(note.textContent).toBe("Partidos no incluidos en el cálculoNota A.");
  });

  test("renders nothing without notes", () => {
    const { container } = render(<ExcludedPartiesNotice notes={[]} />);
    expect(container.innerHTML).toBe("");
  });
});
