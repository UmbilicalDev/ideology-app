import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";

import { HomePage } from "./HomePage";

afterEach(() => {
  cleanup();
});

describe("HomePage", () => {
  test("shows the heading and the placeholder text inside main", () => {
    render(<HomePage />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.textContent).toBe("Comparador de programas electorales");
    const main = screen.getByRole("main");
    expect(main.contains(heading)).toBe(true);
    expect(main.querySelector("p")?.textContent).toBe(
      "Esta aplicación está en construcción. Pronto podrás responder a una serie de afirmaciones " +
        "generadas con IA y ver qué partidos se acercan más a tus respuestas.",
    );
  });

  test("has nothing interactive", () => {
    render(<HomePage />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  });
});
