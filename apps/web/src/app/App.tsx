// Composition root: the route table. `main.tsx` provides the router and the
// public API client (read-only `PublicApi` plus `sendFeedback`); pages
// receive `api` as a prop and never call fetch.
import { Route, Routes } from "react-router";

import type { PublicApiClient } from "@ideology-app/core";

import { LandingPage } from "../features/landing/LandingPage";
import { MethodologyPage } from "../features/methodology/MethodologyPage";
import { NotFoundPage } from "../features/not-found/NotFoundPage";
import { HOME_PATH, METHODOLOGY_PATH, QUESTIONNAIRE_ROUTE, SHARED_RESULTS_PATH } from "../features/paths";
import { QuestionnairePage } from "../features/questionnaire/QuestionnairePage";
import { SharedResultsPage } from "../features/share/SharedResultsPage";

export function App({ api }: { readonly api: PublicApiClient }) {
  return (
    <Routes>
      <Route path={HOME_PATH} element={<LandingPage api={api} />} />
      <Route path={METHODOLOGY_PATH} element={<MethodologyPage />} />
      <Route path={QUESTIONNAIRE_ROUTE} element={<QuestionnairePage api={api} />} />
      <Route path={SHARED_RESULTS_PATH} element={<SharedResultsPage api={api} />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
