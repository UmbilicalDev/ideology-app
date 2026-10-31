// Formatting for the admin page: dates in UTC, origins as screen names.
import type { FeedbackOriginCode } from "./admin-api";

const DATE_TIME = new Intl.DateTimeFormat("es-ES", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** `2026-10-29T14:05:00Z` -> `29 oct 2026, 14:05 UTC`. */
export function formatUtcDateTime(iso: string): string {
  const parts: Record<string, string> = {};
  for (const part of DATE_TIME.formatToParts(new Date(iso))) {
    parts[part.type] = part.value;
  }
  const month = (parts.month ?? "").replace(/\.$/, "");
  return `${parts.day} ${month} ${parts.year}, ${parts.hour}:${parts.minute} UTC`;
}

const ORIGIN_LABELS: Record<FeedbackOriginCode, string> = {
  landing: "General",
  results: "Resultados",
};

export function originLabel(origin: FeedbackOriginCode): string {
  return ORIGIN_LABELS[origin];
}

/** `N mensajes mostrados` (singular for one). */
export function shownCount(count: number): string {
  return count === 1 ? "1 mensaje mostrado" : `${count} mensajes mostrados`;
}

/** Whole minutes to wait, at least 1. */
export function retryMinutes(seconds: number | undefined): number {
  if (seconds === undefined || !Number.isFinite(seconds)) {
    return 15;
  }
  return Math.max(1, Math.ceil(seconds / 60));
}
