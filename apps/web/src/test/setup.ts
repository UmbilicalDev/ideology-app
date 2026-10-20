// Web tests never reach the network: global fetch throws, and tests inject a
// mocked FetchLike into createPublicApiClient instead.
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  vi.stubGlobal("fetch", () => {
    throw new Error("network access is blocked in web tests");
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
