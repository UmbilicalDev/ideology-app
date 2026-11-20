import type { Election } from "@ideology-app/core";

/**
 * The Election the Landing offers (ui-2026-focus-tweaks): the one with the
 * latest `date` (ISO `YYYY-MM-DD`, so a string comparison orders it), the
 * higher `id` on equal dates, `null` for an empty list. Older Elections stay
 * reachable by URL and Share Links; this only picks what the Landing shows.
 */
export function currentElection(elections: readonly Election[]): Election | null {
  let current: Election | null = null;
  for (const election of elections) {
    if (
      current === null ||
      election.date > current.date ||
      (election.date === current.date && election.id > current.id)
    ) {
      current = election;
    }
  }
  return current;
}
