import { InfoIcon } from "../../ui/icons";

/** An informative notice in a card with a decorative info tile (DESIGN.md "Notice card"). */
export function NoticeCard({ text }: { readonly text: string }) {
  return (
    <div className="notice-card">
      <span className="notice-card__icon">
        <InfoIcon />
      </span>
      <p>{text}</p>
    </div>
  );
}
