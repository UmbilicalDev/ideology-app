// Web tests never reach the network: global fetch throws, and tests inject a
// mocked FetchLike into createPublicApiClient instead. jsdom never loads
// images; the logo preload cache is reset after every test.
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { forgetPreloadedPartyLogos } from "../features/results/party-logo-preload";

beforeEach(() => {
  vi.stubGlobal("fetch", () => {
    throw new Error("network access is blocked in web tests");
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  forgetPreloadedPartyLogos();
});
