/**
 * An element's `textContent` without the decorative party-logo tiles, whose
 * placeholder repeats the short name that is already shown as text.
 */
export function textWithoutLogos(element: Element): string {
  const clone = element.cloneNode(true) as Element;
  for (const tile of clone.querySelectorAll(".party-logo")) {
    tile.remove();
  }
  return clone.textContent ?? "";
}
