import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import {
  createPublicApiClient,
  type FeedbackOrigin,
  type FetchLike,
  type HttpResponseLike,
} from "@ideology-app/core";

import { jsonResponse, textResponse } from "../../test/fetch-mocks";
import { FeedbackButton } from "./FeedbackButton";

const TITLE = "Ayúdanos a mejorar";
const SUBTITLE = "Dinos qué te ha parecido IdeologiApp";
const FEEDBACK_URL = "/api/v1/feedback";

function created(): HttpResponseLike {
  return jsonResponse({ status: "ok" }, 201);
}

function renderButton(fetch: FetchLike, origin: FeedbackOrigin = "landing") {
  return render(
    <main>
      <p>Contenido de la página</p>
      <FeedbackButton api={createPublicApiClient({ fetch })} origin={origin} />
    </main>,
  );
}

function trigger() {
  return screen.getByRole("button", { name: "Danos tu opinión" }) as HTMLButtonElement;
}

function openDialog() {
  fireEvent.click(trigger());
  return screen.getByRole("dialog", { name: TITLE, description: SUBTITLE }) as HTMLDialogElement;
}

function textarea() {
  return screen.getByRole("textbox", { name: "Tu opinión" }) as HTMLTextAreaElement;
}

function enviar() {
  return screen.getByRole("button", { name: "Enviar" }) as HTMLButtonElement;
}

function type(value: string) {
  fireEvent.change(textarea(), { target: { value } });
}

function counter() {
  return document.querySelector(".feedback__counter")!;
}

function announcer() {
  return document.querySelector(".feedback__counter ~ p[role='status']")!;
}

function postedBodies(fetch: ReturnType<typeof vi.fn<FetchLike>>) {
  return fetch.mock.calls.map(([url, init]) => {
    expect(url).toBe(FEEDBACK_URL);
    expect(init?.method).toBe("POST");
    return JSON.parse(String(init?.body)) as Record<string, unknown>;
  });
}

function deferred() {
  let resolve: (response: HttpResponseLike) => void = () => {};
  let reject: (error: unknown) => void = () => {};
  const promise = new Promise<HttpResponseLike>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("FeedbackButton and FeedbackDialog", () => {
  test("Scenario 1: the button opens a named, described modal with focus in the text area", () => {
    const fetch = vi.fn<FetchLike>();
    renderButton(fetch);
    expect(trigger().getAttribute("aria-haspopup")).toBe("dialog");
    expect(screen.queryByRole("dialog")).toBeNull();

    const dialog = openDialog();
    expect(dialog.open).toBe(true);
    expect(within(dialog).getByRole("heading", { level: 2, name: TITLE })).toBeTruthy();
    expect(document.activeElement).toBe(textarea());
    expect(textarea().hasAttribute("maxlength")).toBe(false);
    expect(textarea().getAttribute("aria-describedby")).toBe("feedback-hint feedback-limit");
    expect(document.getElementById("feedback-limit")?.textContent).toBe("Máximo 500 caracteres.");
    expect(document.getElementById("feedback-hint")?.textContent).toBe(
      "Solo se guarda el texto, la pantalla desde la que lo envías y la fecha. No escribas " +
        "datos personales.",
    );
    expect(counter().textContent).toBe("0/500");
    expect(counter().getAttribute("aria-hidden")).toBe("true");
    expect(enviar().disabled).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });

  test("Scenario 1: Tab and Shift+Tab wrap inside the dialog", () => {
    renderButton(vi.fn<FetchLike>());
    const dialog = openDialog();
    type("hola");
    const close = within(dialog).getByRole("button", { name: "Cerrar" });
    // Order: close icon button, text area, Enviar (the honeypot is tabIndex -1).
    enviar().focus();
    fireEvent.keyDown(enviar(), { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(enviar());
    // In between, Tab is left to the browser.
    textarea().focus();
    expect(fireEvent.keyDown(textarea(), { key: "Tab" })).toBe(true);
    expect(document.activeElement).toBe(textarea());
  });

  test("Scenario 1: with Enviar disabled, Tab from the text area wraps to the close button", () => {
    renderButton(vi.fn<FetchLike>());
    const dialog = openDialog();
    fireEvent.keyDown(textarea(), { key: "Tab" });
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cerrar" }));
  });

  test("Scenario 1: Escape closes and focus returns to the button", () => {
    renderButton(vi.fn<FetchLike>());
    const dialog = openDialog();
    const cancel = new Event("cancel", { cancelable: true });
    fireEvent(dialog, cancel);
    expect(cancel.defaultPrevented).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  test("Scenario 1: the Cerrar icon button closes and focus returns to the button", () => {
    renderButton(vi.fn<FetchLike>());
    const dialog = openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  test("Scenario 1: a backdrop click closes; a drag-select ending on the backdrop does not", () => {
    renderButton(vi.fn<FetchLike>());
    let dialog = openDialog();
    // Press in the text area, release on the backdrop: the click targets the dialog.
    fireEvent.pointerDown(textarea());
    fireEvent.click(dialog);
    expect(screen.getByRole("dialog")).toBe(dialog);
    // A click inside the surface never closes.
    fireEvent.pointerDown(textarea());
    fireEvent.click(textarea());
    expect(screen.getByRole("dialog")).toBe(dialog);
    // Press and release on the backdrop.
    fireEvent.pointerDown(dialog);
    fireEvent.click(dialog);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger());
    dialog = openDialog();
    expect(dialog.open).toBe(true);
  });

  test("Scenario 1: closing does not wait for the browser's queued close event", () => {
    renderButton(vi.fn<FetchLike>());
    const dialog = openDialog();
    // Browsers fire `close` as a later task; model that by not dispatching it.
    dialog.close = function close(this: HTMLDialogElement) {
      this.removeAttribute("open");
    };
    fireEvent.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger());
    // A late close event from the old element changes nothing.
    fireEvent(dialog, new Event("close"));
    expect(openDialog().open).toBe(true);
  });

  test("a draft survives closing and reopening", () => {
    renderButton(vi.fn<FetchLike>());
    const dialog = openDialog();
    type("Un borrador");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    openDialog();
    expect(textarea().value).toBe("Un borrador");
    expect(counter().textContent).toBe("11/500");
  });

  test("Scenario 2: the counter counts trimmed code points and gates Enviar", () => {
    renderButton(vi.fn<FetchLike>());
    openDialog();
    type("hola ");
    expect(counter().textContent).toBe("4/500");
    expect(enviar().disabled).toBe(false);
    expect(announcer().textContent).toBe("");

    type("   \n  ");
    expect(counter().textContent).toBe("0/500");
    expect(enviar().disabled).toBe(true);
    expect(document.getElementById("feedback-problem")).toBeNull();

    type("a".repeat(450));
    expect(announcer().textContent).toBe("Quedan 50 caracteres o menos.");

    type("😀".repeat(500));
    expect(counter().textContent).toBe("500/500");
    expect(enviar().disabled).toBe(false);
    expect(announcer().textContent).toBe("Has llegado al límite de 500 caracteres.");
    expect(document.getElementById("feedback-problem")).toBeNull();

    type("😀".repeat(501));
    expect(counter().textContent).toBe("501/500");
    expect(counter().className).toContain("feedback__counter--over");
    expect(enviar().disabled).toBe(true);
    expect(announcer().textContent).toBe("Has superado el límite de 500 caracteres.");
    expect(document.getElementById("feedback-problem")?.textContent).toBe(
      "Has superado el límite de 500 caracteres. Borra texto para poder enviar.",
    );
    expect(textarea().getAttribute("aria-describedby")).toBe(
      "feedback-hint feedback-limit feedback-problem",
    );
    // Never truncated.
    expect(Array.from(textarea().value)).toHaveLength(501);
  });

  test("Scenario 3: a pasted tab is sent as a space; a vertical tab disables Enviar", async () => {
    const fetch = vi.fn<FetchLike>(async () => created());
    renderButton(fetch);
    openDialog();
    type("a\u000Bb");
    expect(enviar().disabled).toBe(true);
    expect(document.getElementById("feedback-problem")?.textContent).toBe(
      "El texto tiene caracteres invisibles que no se pueden enviar. Prueba a escribirlo en " +
        "lugar de pegarlo.",
    );
    type("a\tb");
    expect(document.getElementById("feedback-problem")).toBeNull();
    expect(enviar().disabled).toBe(false);
    fireEvent.click(enviar());
    await screen.findByText("¡Gracias por tu opinión!");
    expect(postedBodies(fetch)).toEqual([{ message: "a b", origin: "landing" }]);
  });

  test.each<FeedbackOrigin>(["landing", "results"])(
    "Scenario 4: success sends one POST with only message and origin %s, then thanks",
    async (origin) => {
      const pending = deferred();
      const fetch = vi.fn<FetchLike>(() => pending.promise);
      renderButton(fetch, origin);
      const dialog = openDialog();
      type("  Me ha gustado mucho.  ");
      fireEvent.click(enviar());
      fireEvent.click(enviar());
      expect(enviar().disabled).toBe(true);
      expect(within(dialog).getByText("Enviando tu opinión…").getAttribute("role")).toBe("status");
      expect(document.activeElement).toBe(textarea());
      expect(textarea().readOnly).toBe(true);

      await act(async () => {
        pending.resolve(created());
        await pending.promise;
      });
      expect(fetch).toHaveBeenCalledTimes(1);
      const [body] = postedBodies(fetch);
      expect(body).toEqual({ message: "Me ha gustado mucho.", origin });
      expect(Object.keys(body!).sort()).toEqual(["message", "origin"]);

      expect(screen.queryByRole("textbox")).toBeNull();
      expect(within(dialog).getByText("¡Gracias por tu opinión!").id).toBe("feedback-thanks");
      expect(within(dialog).getByText("Nos ayuda a mejorar IdeologiApp.")).toBeTruthy();
      expect(screen.getByRole("dialog", { name: TITLE, description: SUBTITLE })).toBe(dialog);
      const done = within(dialog).getByRole("button", {
        name: "Cerrar",
        description: "¡Gracias por tu opinión!",
      });
      expect(document.activeElement).toBe(done);
      // The header close button is still there too.
      expect(within(dialog).getAllByRole("button", { name: "Cerrar" })).toHaveLength(2);

      fireEvent.click(done);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.activeElement).toBe(trigger());
      openDialog();
      expect(textarea().value).toBe("");
      expect(counter().textContent).toBe("0/500");
      expect(document.activeElement).toBe(textarea());
    },
  );

  test.each<[string, () => Promise<HttpResponseLike>, string]>([
    [
      "429",
      async () => textResponse(429),
      "Se han enviado muchas opiniones en poco tiempo. Espera unos minutos e inténtalo de nuevo.",
    ],
    [
      "422",
      async () => jsonResponse({ detail: "invalid" }, 422),
      "El servidor no ha aceptado el mensaje. Revisa el texto e inténtalo de nuevo.",
    ],
    [
      "500",
      async () => textResponse(500),
      "No se ha podido enviar tu opinión. Inténtalo de nuevo más tarde.",
    ],
    [
      "a rejected fetch",
      () => Promise.reject(new TypeError("Failed to fetch")),
      "No se ha podido enviar tu opinión. Comprueba tu conexión e inténtalo de nuevo.",
    ],
  ])("Scenario 5: %s shows the retry message, keeps the text, and Enviar retries", async (_name, fail, message) => {
    const fetch = vi.fn<FetchLike>();
    fetch.mockImplementationOnce(fail).mockResolvedValueOnce(created());
    renderButton(fetch);
    openDialog();
    type("Mi opinión");
    fireEvent.click(enviar());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(message);
    expect(textarea().value).toBe("Mi opinión");
    expect(textarea().readOnly).toBe(false);
    expect(document.activeElement).toBe(textarea());
    expect(enviar().disabled).toBe(false);
    expect(screen.queryByText("Enviando tu opinión…")).toBeNull();

    fireEvent.click(enviar());
    expect(screen.queryByRole("alert")).toBeNull();
    await screen.findByText("¡Gracias por tu opinión!");
    expect(postedBodies(fetch)).toEqual([
      { message: "Mi opinión", origin: "landing" },
      { message: "Mi opinión", origin: "landing" },
    ]);
  });

  test("Scenario 5: the alert clears on the next edit", async () => {
    const fetch = vi.fn<FetchLike>(async () => textResponse(500));
    renderButton(fetch);
    openDialog();
    type("Mi opinión");
    fireEvent.click(enviar());
    await screen.findByRole("alert");
    type("Mi opinión.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("Scenario 6: a filled honeypot is sent as website; an empty one is absent", async () => {
    const fetch = vi.fn<FetchLike>(async () => created());
    renderButton(fetch);
    let dialog = openDialog();
    const honeypot = dialog.querySelector<HTMLInputElement>("#feedback-website")!;
    expect(honeypot.tabIndex).toBe(-1);
    expect(honeypot.getAttribute("autocomplete")).toBe("off");
    expect(honeypot.closest("[aria-hidden='true']")).not.toBeNull();
    fireEvent.change(honeypot, { target: { value: "http://spam.example" } });
    type("Hola");
    fireEvent.click(enviar());
    await screen.findByText("¡Gracias por tu opinión!");

    fireEvent.click(within(dialog).getAllByRole("button", { name: "Cerrar" })[1]!);
    dialog = openDialog();
    expect(dialog.querySelector<HTMLInputElement>("#feedback-website")!.value).toBe("");
    type("Adiós");
    fireEvent.click(enviar());
    await screen.findByText("¡Gracias por tu opinión!");
    expect(postedBodies(fetch)).toEqual([
      { message: "Hola", origin: "landing", website: "http://spam.example" },
      { message: "Adiós", origin: "landing" },
    ]);
  });

  test("closing during a send still applies the result", async () => {
    const pending = deferred();
    const fetch = vi.fn<FetchLike>(() => pending.promise);
    renderButton(fetch);
    const dialog = openDialog();
    type("Hola");
    fireEvent.click(enviar());
    fireEvent.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => {
      pending.reject(new TypeError("Failed to fetch"));
      await pending.promise.catch(() => {});
    });
    expect(document.activeElement).toBe(trigger());
    openDialog();
    expect(textarea().value).toBe("Hola");
    expect(screen.getByRole("alert").textContent).toBe(
      "No se ha podido enviar tu opinión. Comprueba tu conexión e inténtalo de nuevo.",
    );
  });
});
