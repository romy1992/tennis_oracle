import { useState } from "react";

type Props = {
  label: string;
  value?: string;
  onChange?: (value: string) => void;
  /** Se presente, il valore vero si chiede al server solo al primo clic sull'occhio. */
  onReveal?: () => Promise<string | null | undefined>;
  autoComplete?: string;
  disabled?: boolean;
  required?: boolean;
  placeholder?: string;
};

const HIDDEN = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022";

export function SecretField({
  label,
  value = "",
  onChange,
  onReveal,
  autoComplete = "off",
  disabled,
  required,
  placeholder
}: Props) {
  const [visible, setVisible] = useState(false);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setError(null);
    if (visible) {
      setVisible(false);
      return;
    }
    if (onReveal && revealed === null) {
      setLoading(true);
      try {
        const plain = await onReveal();
        if (!plain) {
          setError("Non disponibile: reimposta il valore una volta per poterlo vedere.");
          return;
        }
        setRevealed(plain);
      } catch {
        setError("Impossibile leggere il valore.");
        return;
      } finally {
        setLoading(false);
      }
    }
    setVisible(true);
  }

  const shown = onReveal ? (visible ? revealed ?? "" : HIDDEN) : value;
  return (
    <label>
      {label}
      <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type={onReveal || visible ? "text" : "password"}
          value={shown}
          onChange={onChange ? (event) => onChange(event.target.value) : undefined}
          readOnly={Boolean(onReveal)}
          autoComplete={autoComplete}
          disabled={disabled}
          required={required}
          placeholder={placeholder}
          style={{ flex: 1 }}
        />
        <button
          type="button"
          className="action-button"
          onClick={() => void toggle()}
          disabled={loading}
          aria-label={visible ? `Nascondi ${label}` : `Mostra ${label}`}
          title={visible ? "Nascondi" : "Mostra"}
        >
          {visible ? "\u{1F648}" : "\u{1F441}"}
        </button>
      </span>
      {error ? <small role="alert">{error}</small> : null}
    </label>
  );
}
