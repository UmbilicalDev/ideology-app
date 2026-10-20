import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { createPublicApiClient } from "@ideology-app/core";

import { App } from "./app/App";
import "./ui/global.css";
import "./ui/components.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("missing #root element");
}

// The only place that touches the browser's fetch.
const api = createPublicApiClient({ fetch: (url, init) => window.fetch(url, init) });

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App api={api} />
    </BrowserRouter>
  </StrictMode>,
);
