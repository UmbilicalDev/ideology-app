// feedback-admin Scenario 13: loading, not configured, sign-in and its errors,
// session expiry and sign-out (mocked fetch only).
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { createAdminApiClient } from "./admin-api";
import { AdminApp, NOT_CONFIGURED_TEXT, SESSION_EXPIRED_TEXT } from "./AdminApp";
import { fakeAdminServer, message, response } from "./fake-admin-server";

function renderApp(server: ReturnType<typeof fakeAdminServer>) {
  const api = createAdminApiClient({ fetch: server.fetch });
  return render(<AdminApp api={api} />);
}

async function signIn(password = "contraseña-de-prueba") {
  fireEvent.change(await screen.findByLabelText("Usuario"), { target: { value: "prueba" } });
  fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
}

describe("AdminApp", () => {
  test("shows Cargando… while checking, with the heading focused", async () => {
    const server = fakeAdminServer();
    server.state.hold = true;
    renderApp(server);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Administración" }));
    expect(screen.getByRole("status").textContent).toContain("Cargando…");
    await act(async () => server.release());
    expect((await screen.findByRole("heading", { name: "Iniciar sesión" }))).toBeTruthy();
  });

  test("explains how to configure an account and shows no form", async () => {
    renderApp(fakeAdminServer({ configured: false }));
    expect((await screen.findByText(NOT_CONFIGURED_TEXT))).toBeTruthy();
    expect(screen.queryByLabelText("Usuario")).toBeNull();
    expect(screen.queryByRole("button", { name: "Entrar" })).toBeNull();
  });

  test("the sign-in form has the right fields", async () => {
    renderApp(fakeAdminServer());
    const user = await screen.findByLabelText("Usuario");
    expect(user.getAttribute("autocomplete")).toBe("username");
    expect(user.getAttribute("autocapitalize")).toBe("none");
    expect(user.getAttribute("spellcheck")).toBe("false");
    const password = screen.getByLabelText("Contraseña");
    expect(password.getAttribute("type")).toBe("password");
    expect(password.getAttribute("autocomplete")).toBe("current-password");
  });

  test("wrong credentials clear and focus the password", async () => {
    renderApp(fakeAdminServer());
    await signIn("mala");
    expect((await screen.findByRole("alert")).textContent).toContain("Usuario o contraseña incorrectos.");
    const password = screen.getByLabelText("Contraseña");
    expect((password as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(password);
    expect((screen.getByLabelText("Usuario") as HTMLInputElement).value).toBe("prueba");
  });

  test("Entrar is disabled while signing in", async () => {
    const server = fakeAdminServer();
    renderApp(server);
    await screen.findByLabelText("Usuario");
    server.state.hold = true;
    await signIn();
    expect((screen.getByRole("button", { name: "Entrar" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => server.release());
  });

  test("rate limited says how many minutes", async () => {
    const server = fakeAdminServer();
    renderApp(server);
    await screen.findByLabelText("Usuario");
    server.state.next = () =>
      response(429, { error: { code: "rate_limited", message: "" } }, { "Retry-After": "841" });
    await signIn();
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Demasiados intentos. Vuelve a intentarlo en 15 minutos.",
    );
  });

  test("a network failure asks to try again", async () => {
    const server = fakeAdminServer();
    renderApp(server);
    await screen.findByLabelText("Usuario");
    server.state.next = () => Promise.reject(new TypeError("Failed to fetch"));
    await signIn();
    expect((await screen.findByRole("alert")).textContent).toContain(
      "No se pudo conectar. Inténtalo de nuevo.",
    );
  });

  test("signing in opens the inbox; signing out returns to the form", async () => {
    const server = fakeAdminServer({ messages: [message(1)] });
    renderApp(server);
    await signIn();
    expect((await screen.findByText("Sesión iniciada como prueba"))).toBeTruthy();
    expect((await screen.findByText("Mensaje 1"))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
    expect((await screen.findByRole("heading", { name: "Iniciar sesión" }))).toBeTruthy();
    expect(server.state.signedIn).toBe(false);
    expect(screen.queryByText(SESSION_EXPIRED_TEXT)).toBeNull();
  });

  test("an existing session skips the form", async () => {
    renderApp(fakeAdminServer({ signedIn: true, messages: [message(4)] }));
    expect((await screen.findByText("Mensaje 4"))).toBeTruthy();
    expect(screen.queryByLabelText("Usuario")).toBeNull();
  });

  test.each(["mark", "delete", "more", "filter", "signout"] as const)(
    "a 401 during %s returns to sign-in with the expired notice",
    async (action) => {
      const messages = Array.from({ length: 51 }, (_, i) => message(i + 1));
      const server = fakeAdminServer({ signedIn: true, messages });
      renderApp(server);
      expect((await screen.findByText("Mensaje 51"))).toBeTruthy();
      server.state.signedIn = false;
      if (action === "mark") {
        fireEvent.click(screen.getAllByRole("button", { name: "Marcar como revisado" })[0]!);
      } else if (action === "delete") {
        fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]!);
        fireEvent.click(screen.getByRole("button", { name: "Borrar definitivamente" }));
      } else if (action === "more") {
        fireEvent.click(screen.getByRole("button", { name: "Cargar más" }));
      } else if (action === "filter") {
        fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
      } else {
        fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
      }
      expect((await screen.findByText(SESSION_EXPIRED_TEXT))).toBeTruthy();
      expect((screen.getByRole("heading", { name: "Iniciar sesión" }))).toBeTruthy();
      expect(screen.queryByText("Mensaje 51")).toBeNull();
    },
  );

  test("a server restarted without accounts shows the not-configured notice", async () => {
    const server = fakeAdminServer({ signedIn: true, messages: [message(1)] });
    renderApp(server);
    await screen.findByText("Mensaje 1");
    server.state.configured = false;
    fireEvent.click(screen.getByRole("button", { name: "Marcar como revisado" }));
    await waitFor(() => expect(screen.getByText(NOT_CONFIGURED_TEXT)).toBeTruthy());
  });
});
