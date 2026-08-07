import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  message: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, message, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <Icon aria-hidden="true" size={31} strokeWidth={1.8} />
      <h3>{title}</h3>
      <p>{message}</p>
      {action}
    </div>
  );
}
