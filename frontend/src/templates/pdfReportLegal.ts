/**
 * Legal footer strings for PDF export templates.
 * TODO(legal-review): disclaimer text pending legal review
 */
import { COPYRIGHT_VERBATIM, DISCLAIMER_VERBATIM } from "../constants";

export const PDF_DISCLAIMER = DISCLAIMER_VERBATIM;
export const PDF_COPYRIGHT = COPYRIGHT_VERBATIM;

/** Two-line footer block for scan/report PDF layouts. */
export function pdfReportFooterLines(): readonly [string, string] {
  return [PDF_DISCLAIMER, PDF_COPYRIGHT] as const;
}
