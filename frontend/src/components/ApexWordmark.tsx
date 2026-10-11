import { Link } from "react-router-dom";

type Props = {
  linked?: boolean;
  testId?: string;
};

/** Gold APEX wordmark used on every signed-in screen. Click opens Portfolio. */
export function ApexWordmark({ linked = true, testId = "apex-brand" }: Props) {
  const image = (
    <img src="/brand/apex-wordmark.png" alt="APEX" className="desk-wordmark" data-testid="apex-wordmark" />
  );
  if (!linked) return image;
  return (
    <Link to="/portfolio" className="desk-brand" aria-label="Open portfolio" data-testid={testId}>
      {image}
    </Link>
  );
}
