import { useParams } from "react-router";

import type { FeedbackApi, PublicApi } from "@ideology-app/core";

import { HomeButton } from "../common/HomeButton";
import { NotFoundPage } from "../not-found/NotFoundPage";
import { parseElectionId } from "../paths";
import { FocusShell } from "../shell/FocusShell";
import { QuestionnaireFlow } from "./QuestionnaireFlow";
import { useQuestionnaireData } from "./useQuestionnaireData";

// Questionnaire route (`/elecciones/:electionId/cuestionario`), in the focus
// shell (no sidebar). An invalid id is not found without any request.
export function QuestionnairePage({ api }: { readonly api: PublicApi & FeedbackApi }) {
  const { electionId: raw } = useParams();
  const electionId = parseElectionId(raw);
  return (
    <FocusShell>
      {electionId === null ? (
        <NotFoundPage />
      ) : (
        <QuestionnaireLoader key={electionId} api={api} electionId={electionId} />
      )}
    </FocusShell>
  );
}

function QuestionnaireLoader({
  api,
  electionId,
}: {
  readonly api: PublicApi & FeedbackApi;
  readonly electionId: number;
}) {
  const { state, retry } = useQuestionnaireData(api, electionId);
  if (state.kind === "not_found") {
    return <NotFoundPage />;
  }
  // The page title is the Election's name once it is known.
  return (
    <main className="questionnaire">
      <h1 className="questionnaire__election">
        {state.kind === "ready" ? state.election.name : "Cuestionario"}
      </h1>
      {(() => {
        switch (state.kind) {
          case "loading":
            return <p role="status">Cargando cuestionario…</p>;
          case "unavailable":
            return (
              <>
                <p>
                  El cuestionario de estas elecciones todavía no está disponible. Vuelve a
                  consultarlo más adelante.
                </p>
                <HomeButton />
              </>
            );
          case "error":
            return (
              <>
                <div role="alert">
                  <p>
                    No se ha podido cargar el cuestionario. Comprueba tu conexión e inténtalo de
                    nuevo.
                  </p>
                  <button type="button" className="button-primary" onClick={retry}>
                    Reintentar
                  </button>
                </div>
                <HomeButton />
              </>
            );
          case "ready":
            return (
              <QuestionnaireFlow
                key={state.datasetVersion.id}
                datasetVersion={state.datasetVersion}
                feedbackApi={api}
              />
            );
        }
      })()}
    </main>
  );
}
