export type ReadingSize = "large" | "larger";
export type ParticipantRole = "participant" | "caregiver";

export interface ParticipantSessionInput {
  user_id: string;
  role: ParticipantRole;
  caregiver_name?: string;
  caregiver_mobile?: string;
  preferences?: {
    reading_size: ReadingSize;
    voice_enabled: boolean;
    activity_memory_enabled?: boolean;
    proactive_reminders_enabled?: boolean;
  };
}

export interface ParticipantContext {
  participantSessionId: string;
  userId: string;
  displayName: string;
  role: ParticipantRole;
  accessToken?: string;
  readingSize: ReadingSize;
  voiceEnabled: boolean;
  activityMemoryEnabled: boolean;
  proactiveRemindersEnabled: boolean;
}

export interface CapabilityReadiness {
  name: string;
  state?: string;
  configured: boolean;
  reachable: boolean;
  authorized: boolean;
  lastCheckedAt?: string;
  latencyMs?: number;
  errorCode?: string;
  detail?: string;
}

export interface ReadinessSnapshot {
  ready: boolean;
  mode?: string;
  capabilities: CapabilityReadiness[];
  checkedAt?: string;
}

export interface Routine {
  id: string;
  name: string;
  description?: string;
  skillId?: string;
  revision?: number;
  startOrigin?: string;
  lastCompletedAt?: string;
  replayReady: boolean;
}

export interface ProactiveReminder {
  id: string;
  routine: Routine;
  reason: string;
  dueAt: string;
  recurrence: "daily" | "weekly" | "monthly";
  typicalLocalTime: string;
  occurrenceCount: number;
  overdueDays: number;
  permissionRequired: true;
}

export interface DemoTask {
  id: string;
  name: string;
  description: string;
  startUrl: string;
  prompt: string;
  category: "appointment" | "shopping" | "government";
}

export type AgentActionKind =
  | "click"
  | "fill"
  | "select"
  | "check"
  | "press"
  | "navigate"
  | "scroll"
  | "wait"
  | "done"
  | "ask";

export type AgentStepStatus = "running" | "done" | "failed" | "blocked";

export interface AgentStep {
  stepNo: number;
  action: AgentActionKind;
  narration: string;
  status: AgentStepStatus;
  detail?: string;
  pageTitle?: string;
  origin?: string;
  occurredAt?: string;
}

export type AgentRunState =
  | "running"
  | "needs_confirmation"
  | "completed"
  | "failed"
  | "stopped";

export interface AgentRun {
  sessionId: string;
  taskName: string;
  state: AgentRunState;
  steps: AgentStep[];
  pageTitle?: string;
  origin?: string;
  redactedPath?: string;
  pendingConfirmation?: SafetyPresentation;
  summary?: string;
}

export interface AgentRunInput {
  prompt: string;
  demo_id?: string;
  start_url?: string;
}

export interface SkillDocument {
  id: string;
  skillKey?: string;
  name: string;
  revision?: number;
  markdown: string;
  steps: SkillInstruction[];
  sourceSessionId?: string;
  outcome?: string;
  updatedAt?: string;
}

export interface SkillInstruction {
  id: string;
  instruction: string;
}

export interface SkillRevisionInput {
  expected_revision: number;
  name?: string;
  instruction_edits: Array<{ step_id: string; instruction: string }>;
  reason: string;
}

export interface ReviewedBillUpload {
  objectKey: string;
  indexingStatus: "awaiting_memory_add";
  reviewed: true;
}

export type SessionPhase =
  | "created"
  | "observing"
  | "help_offered"
  | "guiding"
  | "awaiting_user_action"
  | "verifying"
  | "rerouting"
  | "repairing"
  | "safety_paused"
  | "escalated"
  | "completed"
  | "prepared"
  | "abandoned"
  | "failed"
  | "provider_unavailable";

export type SafetyClassification =
  | "safe"
  | "money"
  | "identity"
  | "deletion"
  | "suspicious"
  | "unknown";

export interface MoneyAmount {
  value: string;
  currency?: string;
  source?: string;
}

export interface SafetyPresentation {
  classification: SafetyClassification;
  title?: string;
  message?: string;
  actionDescription?: string;
  amount?: MoneyAmount;
}

export interface GuidanceCommand {
  id?: string;
  type?: string;
  instruction?: string;
  safety?: SafetyPresentation;
}

export interface SessionTask {
  id?: string;
  name: string;
  mode?: "cold" | "replay" | "repair" | "observe";
  skillId?: string;
  skillRevision?: number;
}

export interface SessionSnapshot {
  id: string;
  userId?: string;
  participantSessionId?: string;
  browserbaseSessionId?: string;
  pageId?: string;
  pageInstanceId?: string;
  pageOrigin?: string;
  redactedPath?: string;
  nextSequenceNo?: number;
  stateVersion: number;
  phase: SessionPhase;
  task?: SessionTask;
  command?: GuidanceCommand;
  liveViewUrl?: string;
  syncState?: "sync_pending" | "sync_failed" | "synced";
  guidanceMode?: "cold" | "replay" | "repair" | "none";
  outcomeMessage?: string;
  amount?: MoneyAmount;
  completedAt?: string;
  escalationId?: string;
  escalationDelivery?: "pending_delivery" | "sent" | "delivered" | "failed";
  providerErrorCode?: string;
  providerMessage?: string;
}

export interface SessionCreateInput {
  mode: "observe" | "caregiver_record" | "cold_teach" | "replay";
  task_name: string;
  task_intent: string;
  skill_id?: string;
  start_url?: string;
}

export interface EpisodeAnswer {
  found: boolean;
  answer?: string;
  taskName?: string;
  occurredAt?: string;
  amount?: MoneyAmount;
  outcome?: "completed" | "prepared";
}

export interface CaregiverSessionSummary {
  id: string;
  taskName: string;
  participantName?: string;
  startedAt: string;
  endedAt?: string;
  outcome: string;
  guidanceMode?: string;
  syncState?: string;
  escalationId?: string;
  noteCount?: number;
}

export interface CostRun {
  runId: string;
  taskName: string;
  runNumber?: number;
  mode: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  costUsd?: number;
  latencyMs?: number;
  occurredAt?: string;
  synced: boolean;
}

export interface CaregiverHistoryResponse {
  sessions: CaregiverSessionSummary[];
}

export interface CostRunsResponse {
  runs: CostRun[];
  currency: string;
  source?: string;
}

export interface CaregiverNote {
  id: string;
  authorName: string;
  message: string;
  createdAt?: string;
  deliveryStatus?: string;
}

export interface CaregiverPanelNote {
  authorName: string;
  text: string;
}

export interface SessionEventInput {
  eventType:
    | "help_requested"
    | "guidance_presented"
    | "guidance_dismissed"
    | "task_abandoned";
  payload?: Record<string, unknown>;
}
