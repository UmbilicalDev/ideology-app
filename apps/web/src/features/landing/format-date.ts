const FORMATTER = new Intl.DateTimeFormat("es-ES", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

/** Formats a `YYYY-MM-DD` Election date in Spanish, e.g. `23 de julio de 2023`. */
export function formatElectionDate(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  if (year === undefined || month === undefined || day === undefined) {
    return date;
  }
  return FORMATTER.format(new Date(Date.UTC(year, month - 1, day)));
}
