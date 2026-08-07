import type { SessionPhase } from "../api/types";

export interface PhasePresentation {
  label: string;
  tone: "neutral" | "active" | "success" | "warning" | "danger";
  busy: boolean;
}

export const phasePresentation: Record<SessionPhase, PhasePresentation> = {
  created: { label: "Starting", tone: "neutral", busy: true },
  observing: { label: "Watching quietly", tone: "neutral", busy: false },
  help_offered: { label: "Help is ready", tone: "active", busy: false },
  guiding: { label: "Next step", tone: "active", busy: false },
  awaiting_user_action: { label: "Waiting for you", tone: "active", busy: false },
  verifying: { label: "Checking", tone: "neutral", busy: true },
  rerouting: { label: "Finding the way back", tone: "warning", busy: true },
  repairing: { label: "Updating this step", tone: "warning", busy: true },
  safety_paused: { label: "Paused", tone: "warning", busy: false },
  escalated: { label: "Caregiver help", tone: "warning", busy: false },
  completed: { label: "Finished", tone: "success", busy: false },
  prepared: { label: "Ready for confirmation", tone: "success", busy: false },
  abandoned: { label: "Task stopped", tone: "neutral", busy: false },
  failed: { label: "Could not continue", tone: "danger", busy: false },
  provider_unavailable: { label: "Browser unavailable", tone: "danger", busy: false },
};

export function isTerminalPhase(phase: SessionPhase): boolean {
  return ["completed", "prepared", "escalated", "abandoned", "failed", "provider_unavailable"].includes(phase);
}
