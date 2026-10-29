// feedback-admin Scenario 13: the list, filters, paging, mark/unmark and the
// inline delete confirmation (mocked fetch only).
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { createAdminApiClient } from "./admin-api";
import { fakeAdminServer, message, type FakeMessage } from "./fake-admin-server";
import {
  DELETED_TEXT,
  EMPTY_TEXT,
  FeedbackInbox,
  NO_MATCH_TEXT,
  RANGE_PROBLEM_TEXT,
} from "./FeedbackInbox";
import { CONFIRM_TEXT } from "./FeedbackMessageCard";
import { formatUtcDateTime, originLabel } from "./format";

/** As after AdminApp's session check: the client holds the CSRF token. */
async function renderInbox(messages: FakeMessage[]) {
  const server = fakeAdminServer({ signedIn: true, messages });
  const api = createAdminApiClient({ fetch: server.fetch });
  await api.getSession();
  server.state.calls.length = 0;
  const callbacks = { onSessionExpired: vi.fn(), onNotConfigured: vi.fn(), onSignedOut: vi.fn() };
  render(<FeedbackInbox api={api} username="prueba" {...callbacks} />);
  return { server, callbacks };
}

function cards(): HTMLElement[] {
  return within(screen.getByRole("list", { name: "Mensajes" })).getAllByRole("article");
}

describe("format", () => {
  test("dates are UTC in Spanish", () => {
    expect(formatUtcDateTime("2026-10-29T14:05:00Z")).toBe("29 oct 2026, 14:05 UTC");
    expect(formatUtcDateTime("2026-01-01T00:00:59Z")).toBe("1 ene 2026, 00:00 UTC");
    expect(formatUtcDateTime("2026-10-29T23:59:00Z")).toBe("29 oct 2026, 23:59 UTC");
  });

  test("origins are screen names", () => {
    expect(originLabel("landing")).toBe("Inicio");
    expect(originLabel("results")).toBe("Resultados");
  });
});

describe("FeedbackInbox", () => {
  test("lists messages newest first with date, origin, chip and literal text", async () => {
    await renderInbox([
      message(1, { created_at: "2026-10-29T14:05:00Z", origin: "landing" }),
      message(2, {
        created_at: "2026-10-29T15:30:00Z",
        origin: "results",
        message: "Hola <b>negrita</b>\nsegunda línea",
        reviewed_at: "2026-10-29T16:00:00Z",
      }),
    ]);
    await screen.findByText("2 mensajes mostrados");
    const [second, first] = cards() as [HTMLElement, HTMLElement];
    expect(first.textContent).toContain("#1 · 29 oct 2026, 14:05 UTC · Inicio");
    expect(second.textContent).toContain("#2 · 29 oct 2026, 15:30 UTC · Resultados");
    expect(within(second!).getByText("Revisado").classList.contains("important-mark")).toBe(true);
    expect(within(first!).queryByText("Revisado")).toBeNull();
    const text = second!.querySelector(".admin-message__text")!;
    expect(text.textContent).toBe("Hola <b>negrita</b>\nsegunda línea");
    expect(second!.querySelector("b")).toBeNull();
    expect((within(second!).getByRole("button", { name: "Marcar como no revisado" }) as HTMLButtonElement).disabled).toBe(false);
    expect((within(first!).getByRole("button", { name: "Marcar como revisado" }) as HTMLButtonElement).disabled).toBe(false);
  });

  test("empty store and no match have their own text", async () => {
    await renderInbox([]);
    expect((await screen.findByText(EMPTY_TEXT))).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "yes" } });
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    expect((await screen.findByText(NO_MATCH_TEXT))).toBeTruthy();
  });

  test("filters send their query and Hasta before Desde sends nothing", async () => {
    const { server } = await renderInbox([
      message(1, { created_at: "2026-10-01T10:00:00Z" }),
      message(2, { created_at: "2026-10-05T10:00:00Z", reviewed_at: "2026-10-06T10:00:00Z" }),
      message(3, { created_at: "2026-10-09T10:00:00Z" }),
    ]);
    await screen.findByText("3 mensajes mostrados");
    expect(server.state.calls.at(-1)!.url).toBe("/admin/api/v1/feedback?reviewed=all");
    fireEvent.change(screen.getByLabelText("Desde (UTC)"), { target: { value: "2026-10-05" } });
    fireEvent.change(screen.getByLabelText("Hasta (UTC)"), { target: { value: "2026-10-04" } });
    const before = server.state.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    expect((await screen.findByRole("alert")).textContent).toContain(RANGE_PROBLEM_TEXT);
    expect(server.state.calls.length).toBe(before);
    fireEvent.change(screen.getByLabelText("Hasta (UTC)"), { target: { value: "2026-10-09" } });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "no" } });
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    await screen.findByText("1 mensaje mostrado");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(server.state.calls.at(-1)!.url).toBe(
      "/admin/api/v1/feedback?from=2026-10-05&to=2026-10-09&reviewed=no",
    );
    expect(cards().map((c) => c.getAttribute("aria-label"))).toEqual(["Mensaje #3"]);
  });

  test("Cargar más appends the next page and disappears at the end", async () => {
    const { server } = await renderInbox(Array.from({ length: 60 }, (_, i) => message(i + 1)));
    await screen.findByText("50 mensajes mostrados");
    expect(cards()[0]?.getAttribute("aria-label")).toBe("Mensaje #60");
    expect(cards().at(-1)?.getAttribute("aria-label")).toBe("Mensaje #11");
    fireEvent.click(screen.getByRole("button", { name: "Cargar más" }));
    await screen.findByText("60 mensajes mostrados");
    expect(server.state.calls.at(-1)!.url).toBe("/admin/api/v1/feedback?reviewed=all&before_id=11");
    expect(cards().at(-1)?.getAttribute("aria-label")).toBe("Mensaje #1");
    expect(screen.queryByRole("button", { name: "Cargar más" })).toBeNull();
  });

  test("mark and unmark show the pending state", async () => {
    const { server } = await renderInbox([message(1)]);
    await screen.findByText("1 mensaje mostrado");
    server.state.hold = true;
    fireEvent.click(screen.getByRole("button", { name: "Marcar como revisado" }));
    const pending = screen.getByRole("button", { name: "Marcar como revisado" });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    expect(pending.getAttribute("aria-busy")).toBe("true");
    expect((screen.getByRole("button", { name: "Borrar" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => server.release());
    const unmark = await screen.findByRole("button", { name: "Marcar como no revisado" });
    expect((unmark as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("Revisado")).toBeTruthy();
    server.state.hold = false;
    fireEvent.click(unmark);
    expect((await screen.findByRole("button", { name: "Marcar como revisado" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("Revisado")).toBeNull();
    expect(server.state.messages[0]!.reviewed_at).toBeNull();
  });

  test("delete confirms inline; Escape and Cancelar restore focus to Borrar", async () => {
    const { server } = await renderInbox([message(1), message(2), message(3)]);
    await screen.findByText("3 mensajes mostrados");
    const card = () => cards().find((c) => c.getAttribute("aria-label") === "Mensaje #2")!;
    fireEvent.click(within(card()).getByRole("button", { name: "Borrar" }));
    expect(within(card()).getByText(CONFIRM_TEXT)).toBeTruthy();
    expect(document.activeElement).toBe(within(card()).getByRole("button", { name: "Cancelar" }));
    expect(within(card()).queryByRole("button", { name: "Marcar como revisado" })).toBeNull();
    fireEvent.keyDown(within(card()).getByRole("button", { name: "Cancelar" }), { key: "Escape" });
    expect(document.activeElement).toBe(within(card()).getByRole("button", { name: "Borrar" }));
    fireEvent.click(within(card()).getByRole("button", { name: "Borrar" }));
    fireEvent.click(within(card()).getByRole("button", { name: "Cancelar" }));
    expect(document.activeElement).toBe(within(card()).getByRole("button", { name: "Borrar" }));
    expect(server.state.messages).toHaveLength(3);

    fireEvent.click(within(card()).getByRole("button", { name: "Borrar" }));
    fireEvent.click(within(card()).getByRole("button", { name: "Borrar definitivamente" }));
    await screen.findByText(DELETED_TEXT);
    expect(screen.getByRole("status").textContent).toContain(DELETED_TEXT);
    expect(cards().map((c) => c.getAttribute("aria-label"))).toEqual(["Mensaje #3", "Mensaje #1"]);
    expect(server.state.messages.map((m) => m.id)).toEqual([1, 3]);
    // Focus moves to the next card's first action.
    await waitFor(() =>
      expect(document.activeElement).toBe(within(cards()[1]!).getByRole("button", { name: "Marcar como revisado" })),
    );
  });

  test("deleting the last message focuses the status line", async () => {
    await renderInbox([message(1)]);
    await screen.findByText("1 mensaje mostrado");
    fireEvent.click(screen.getByRole("button", { name: "Borrar" }));
    fireEvent.click(screen.getByRole("button", { name: "Borrar definitivamente" }));
    await screen.findByText(DELETED_TEXT);
    expect(document.activeElement).toBe(screen.getByRole("status"));
    expect(screen.queryByRole("list", { name: "Mensajes" })).toBeNull();
  });

  test("a load error offers Reintentar", async () => {
    const server = fakeAdminServer({ signedIn: true, messages: [message(1)] });
    server.state.next = () => Promise.reject(new TypeError("Failed to fetch"));
    const api = createAdminApiClient({ fetch: server.fetch });
    render(
      <FeedbackInbox
        api={api}
        username="prueba"
        onSessionExpired={vi.fn()}
        onNotConfigured={vi.fn()}
        onSignedOut={vi.fn()}
      />,
    );
    expect((await screen.findByRole("alert")).textContent).toContain("No se pudieron cargar los mensajes.");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect((await screen.findByText("Mensaje 1"))).toBeTruthy();
  });

  test("an action error stays inside its card", async () => {
    const { server } = await renderInbox([message(1), message(2)]);
    await screen.findByText("2 mensajes mostrados");
    server.state.next = () => Promise.reject(new TypeError("Failed to fetch"));
    const target = cards()[1]!;
    fireEvent.click(within(target).getByRole("button", { name: "Marcar como revisado" }));
    expect((await within(target).findByRole("alert")).textContent).toContain(
      "No se pudo completar la acción. Inténtalo de nuevo.",
    );
    expect(within(cards()[0]!).queryByRole("alert")).toBeNull();
  });
});
