// The topic catalog (topic-catalog): the 18 stable topic keys with their Spanish
// names, in citizen-priority display order (CIS estudio 3587, Pregunta 6R).
// The data is generated from src/ideology_app/topic_catalog.py; see
// topic-catalog.generated.ts.
import { TOPIC_CATALOG } from "./topic-catalog.generated";
import type { TopicKey } from "./topic-catalog.generated";

export { TOPIC_CATALOG };
export type { TopicKey };

export type TopicEntry = (typeof TOPIC_CATALOG)[number];

// The catalog entry for a key, or undefined for a key the catalog does not
// have (old or dev data may hold any string as a Statement topic).
export function findTopic(key: string): TopicEntry | undefined {
  return TOPIC_CATALOG.find((entry) => entry.key === key);
}
