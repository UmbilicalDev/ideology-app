// Web tests never reach the network: global fetch throws, and tests inject a
// mocked FetchLike into createPublicApiClient instead. jsdom never loads
// images; the logo preload cache is reset after every test. jsdom has no
// `HTMLDialogElement.showModal`/`close`: minimal stand-ins are defined only
// when missing (no top layer or inert page; tests check focus themselves).
// jsdom does not implement media playback: `play`/`pause` on <video> are
// silent stubs (play resolves) that tests can spy on.
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { forgetPreloadedPartyLogos } from "../features/results/party-logo-preload";

if (typeof HTMLDialogElement.prototype.showModal !== "function") {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
}
if (typeof HTMLDialogElement.prototype.close !== "function") {
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.hasAttribute("open")) {
      return;
    }
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.stubGlobal("fetch", () => {
    throw new Error("network access is blocked in web tests");
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  forgetPreloadedPartyLogos();
});
