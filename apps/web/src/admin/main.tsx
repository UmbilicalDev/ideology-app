// Entry of the Operator admin page (apps/web/admin/index.html). The only
// place besides src/main.tsx that touches the browser's fetch, and only for
// createAdminApiClient. No Voter page imports anything from src/admin/.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createAdminApiClient } from "./admin-api";
import { AdminApp } from "./AdminApp";
// Inter, self-hosted: Vite emits the woff2 files to /assets/ (no third-party request).
import "@fontsource-variable/inter/wght.css";
import "../ui/global.css";
import "../ui/components.css";
import "../ui/admin.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("missing #root element");
}

const api = createAdminApiClient({ fetch: (url, init) => window.fetch(url, init) });

createRoot(root).render(
  <StrictMode>
    <AdminApp api={api} />
  </StrictMode>,
);
