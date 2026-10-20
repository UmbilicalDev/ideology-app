import { Link, useParams } from "react-router";

import { NotFoundPage } from "../not-found/NotFoundPage";
import { HOME_PATH, parseElectionId } from "../paths";

// Placeholder for the Questionnaire route; `questionnaire-answer-flow`
// replaces it. It makes no API call.
export function QuestionnairePlaceholderPage() {
  const { electionId } = useParams();
  if (parseElectionId(electionId) === null) {
    return <NotFoundPage />;
  }
  return (
    <main>
      <h1>Cuestionario</h1>
      <p>El cuestionario de estas elecciones estará disponible muy pronto.</p>
      <p>
        <Link className="back-link" to={HOME_PATH}>
          Volver al inicio
        </Link>
      </p>
    </main>
  );
}
