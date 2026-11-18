// Composition root: the route table. `main.tsx` provides the router and the
// public API client (read-only `PublicApi` plus `sendFeedback`); pages
// receive `api` as a prop and never call fetch. Every page but the
// Questionnaire sits in the app shell (DESIGN.md "App shell"); the
// Questionnaire brings its own focus shell. The donation link is loaded once
// here (donate-buymeacoffee) and shared through `DonationUrlContext`.
import { Route, Routes } from "react-router";

import type { PublicApiClient } from "@ideology-app/core";

import { DonationUrlContext } from "../features/donate/donation-context";
import { useDonationUrl } from "../features/donate/useDonationUrl";
import { LandingPage } from "../features/landing/LandingPage";
import { LegalPage } from "../features/legal/LegalPage";
import { MethodologyPage } from "../features/methodology/MethodologyPage";
import { NotFoundPage } from "../features/not-found/NotFoundPage";
import {
  HOME_PATH,
  LEGAL_PATH,
  METHODOLOGY_PATH,
  QUESTIONNAIRE_ROUTE,
  SHARED_RESULTS_PATH,
  TRANSPARENCY_PATH,
} from "../features/paths";
import { QuestionnairePage } from "../features/questionnaire/QuestionnairePage";
import { SharedResultsPage } from "../features/share/SharedResultsPage";
import { AppShell } from "../features/shell/AppShell";
import { TransparencyPage } from "../features/transparency/TransparencyPage";

export function App({ api }: { readonly api: PublicApiClient }) {
  const donationUrl = useDonationUrl(api);
  return (
    <DonationUrlContext.Provider value={donationUrl}>
      <Routes>
        <Route element={<AppShell api={api} />}>
          <Route path={HOME_PATH} element={<LandingPage api={api} />} />
          <Route path={METHODOLOGY_PATH} element={<MethodologyPage />} />
          <Route path={TRANSPARENCY_PATH} element={<TransparencyPage />} />
          <Route path={LEGAL_PATH} element={<LegalPage api={api} />} />
          <Route path={SHARED_RESULTS_PATH} element={<SharedResultsPage api={api} />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
        <Route path={QUESTIONNAIRE_ROUTE} element={<QuestionnairePage api={api} />} />
      </Routes>
    </DonationUrlContext.Provider>
  );
}
