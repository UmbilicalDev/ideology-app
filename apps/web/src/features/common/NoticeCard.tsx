import { InfoIcon, TestTubeIcon } from "../../ui/icons";

/**
 * An informative notice in a card with a decorative tile (DESIGN.md "Notice
 * card"): an info icon by default; the warning tone (the Landing trial
 * notice) uses a test tube on the amber warning pair and may add a title.
 */
export function NoticeCard({
  text,
  title,
  tone = "info",
}: {
  readonly text: string;
  readonly title?: string;
  readonly tone?: "info" | "warning";
}) {
  return (
    <div className={tone === "warning" ? "notice-card notice-card--warning" : "notice-card"}>
      <span className="notice-card__icon">
        {tone === "warning" ? <TestTubeIcon /> : <InfoIcon />}
      </span>
      {title === undefined ? (
        <p>{text}</p>
      ) : (
        <div>
          <h3 className="notice-card__title">{title}</h3>
          <p>{text}</p>
        </div>
      )}
    </div>
  );
}
