import { useEffect, useRef, useState } from "react";

type Props = {
  value: string;
  onChange: (v: string) => void;
  autofill?: string | null;
  onAutofillComplete?: () => void;
};

/**
 * Six OTP boxes. Autofill seeds the full code for Verify immediately, then
 * animates the visible digits one-by-one. Visual fill never clears the
 * parent `value` mid-animation (that race used to submit an empty code).
 */
export function OtpBoxes({ value, onChange, autofill, onAutofillComplete }: Props) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const [display, setDisplay] = useState(value);
  const [typing, setTyping] = useState(false);

  useEffect(() => {
    if (!typing) setDisplay(value);
  }, [value, typing]);

  useEffect(() => {
    if (!autofill || autofill.length !== 6) return;
    // Seed full code for verify first — never leave parent as "" / partial.
    onChange(autofill);
    setTyping(true);
    setDisplay("");
    let i = 0;
    const t = window.setInterval(() => {
      i += 1;
      setDisplay(autofill.slice(0, i));
      refs.current[i - 1]?.focus();
      if (i >= 6) {
        window.clearInterval(t);
        setTyping(false);
        setDisplay(autofill);
        refs.current[5]?.focus();
        window.requestAnimationFrame(() => onAutofillComplete?.());
      }
    }, 70);
    return () => {
      window.clearInterval(t);
      setTyping(false);
    };
  }, [autofill]); // eslint-disable-line react-hooks/exhaustive-deps — once per issued code

  function setAt(idx: number, ch: string) {
    setTyping(false);
    const next = value.padEnd(6, " ").split("") as string[];
    next[idx] = ch;
    const joined = next.join("").replace(/ /g, "").slice(0, 6);
    onChange(joined);
    setDisplay(joined);
    if (ch && idx < 5) refs.current[idx + 1]?.focus();
  }

  const shown = typing ? display : value || display;

  return (
    <div className="flex gap-2 justify-center" data-testid="otp-boxes">
      {Array.from({ length: 6 }).map((_, i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current[i] = el;
          }}
          inputMode="numeric"
          maxLength={1}
          aria-label={`Digit ${i + 1}`}
          className="h-12 w-10 rounded-md border border-line bg-ink text-center font-mono text-lg text-champagne focus-visible:border-gold"
          value={shown[i] ?? ""}
          onChange={(e) => setAt(i, e.target.value.replace(/\D/g, "").slice(-1))}
          onKeyDown={(e) => {
            if (e.key === "Backspace" && !shown[i] && i > 0) refs.current[i - 1]?.focus();
          }}
        />
      ))}
    </div>
  );
}
