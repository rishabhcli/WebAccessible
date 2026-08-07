import { CheckCircle2, CircleAlert, CircleDashed, Clock3, WifiOff } from "lucide-react";

export type StatusTone = "neutral" | "active" | "success" | "warning" | "danger";

interface StatusBadgeProps {
  label: string;
  tone?: StatusTone;
  busy?: boolean;
}

export function StatusBadge({ label, tone = "neutral", busy = false }: StatusBadgeProps) {
  const Icon = busy
    ? CircleDashed
    : tone === "success"
      ? CheckCircle2
      : tone === "warning"
        ? Clock3
        : tone === "danger"
          ? WifiOff
          : tone === "active"
            ? CircleAlert
            : CircleDashed;
  return (
    <span className={`status-badge status-badge--${tone}`}>
      <Icon aria-hidden="true" className={busy ? "spin" : undefined} size={17} strokeWidth={2.2} />
      {label}
    </span>
  );
}
