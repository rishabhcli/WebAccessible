import type {
  CapabilityReadiness,
  CaregiverPanelNote,
  CaregiverHistoryResponse,
  CaregiverNote,
  CostRunsResponse,
  EpisodeAnswer,
  ParticipantContext,
  ParticipantSessionInput,
  ProactiveReminder,
  ReadinessSnapshot,
  ReviewedBillUpload,
  Routine,
  SessionCreateInput,
  SessionEventInput,
  SessionPhase,
  SessionSnapshot,
  SkillDocument,
  SkillRevisionInput,
} from "./types";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL = configuredBaseUrl?.replace(/\/$/, "") ?? "";
const STREAM_PATH = import.meta.env.VITE_SESSION_STREAM_PATH ?? "/stream";

type JsonRecord = Record<string, unknown>;

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(record: JsonRecord, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return undefined;
}

function numberValue(record: JsonRecord, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return undefined;
}

function booleanValue(record: JsonRecord, ...keys: string[]): boolean | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "boolean") return value;
  }
  return undefined;
}

function requestUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function phaseFrom(value: unknown): SessionPhase {
  const phase = typeof value === "string" ? value.toLowerCase() : "created";
  const aliases: Record<string, SessionPhase> = {
    help_offer: "help_offered",
    help_offered: "help_offered",
    awaiting_action: "awaiting_user_action",
    safety_pause: "safety_paused",
    disconnected: "provider_unavailable",
    unavailable: "provider_unavailable",
  };
  const supported = new Set<SessionPhase>([
    "created",
    "observing",
    "help_offered",
    "guiding",
    "awaiting_user_action",
    "verifying",
    "rerouting",
    "repairing",
    "safety_paused",
    "escalated",
    "completed",
    "prepared",
    "abandoned",
    "failed",
    "provider_unavailable",
  ]);
  return aliases[phase] ?? (supported.has(phase as SessionPhase) ? (phase as SessionPhase) : "created");
}

function normalizeAmount(value: unknown, currencyValue?: unknown) {
  if ((typeof value === "string" || typeof value === "number") && value !== "") {
    return {
      value: String(value),
      currency: typeof currencyValue === "string" ? currencyValue : undefined,
    };
  }
  if (!isRecord(value)) return undefined;
  const amountValue = stringValue(value, "value", "amount") ??
    (typeof value.value === "number" ? String(value.value) : undefined);
  if (!amountValue) return undefined;
  return {
    value: amountValue,
    currency: stringValue(value, "currency"),
    source: stringValue(value, "source"),
  };
}

function normalizeTaskMode(value: string | undefined): "cold" | "replay" | "repair" | "observe" | undefined {
  if (value === "cold_teach") return "cold";
  if (value === "caregiver_record" || value === "observe") return "observe";
  if (value === "cold" || value === "replay" || value === "repair") return value;
  return undefined;
}

function normalizeGuidanceMode(value: string | undefined): "cold" | "replay" | "repair" | undefined {
  if (value === "cold_teach") return "cold";
  if (value === "cold" || value === "replay" || value === "repair") return value;
  return undefined;
}

export function normalizeSession(value: unknown, commandValue?: unknown): SessionSnapshot {
  if (!isRecord(value)) throw new ApiError("The session response was not valid.", 502, "invalid_response");
  const rawTask = isRecord(value.task) ? value.task : undefined;
  const responseCommand = isRecord(commandValue) ? commandValue : undefined;
  const rawCommand = responseCommand ?? (isRecord(value.current_command)
    ? value.current_command
    : isRecord(value.command)
      ? value.command
      : stringValue(value, "current_instruction", "safety_message", "terminal_message")
        ? {
            command_id: `${stringValue(value, "id", "session_id") ?? "session"}-${numberValue(value, "state_version") ?? 0}`,
            instruction: stringValue(value, "current_instruction"),
            safety: stringValue(value, "safety_message")
              ? { classification: "unknown", message: stringValue(value, "safety_message") }
              : undefined,
          }
        : undefined);
  const rawSafety = rawCommand && isRecord(rawCommand.safety) ? rawCommand.safety : undefined;
  const rawAmount = normalizeAmount(value.amount, value.currency) ?? normalizeAmount(rawSafety?.amount);
  const id = stringValue(value, "session_id", "id");
  if (!id) throw new ApiError("The session response did not include an ID.", 502, "invalid_response");

  return {
    id,
    userId: stringValue(value, "user_id"),
    participantSessionId: stringValue(value, "participant_session_id"),
    browserbaseSessionId: stringValue(value, "browserbase_session_id"),
    pageId: stringValue(value, "page_id"),
    pageInstanceId: stringValue(value, "page_instance_id"),
    pageOrigin: stringValue(value, "origin", "page_origin"),
    redactedPath: stringValue(value, "redacted_path"),
    nextSequenceNo: numberValue(value, "next_sequence_no"),
    stateVersion: numberValue(value, "server_state_version", "state_version") ?? 0,
    phase: phaseFrom(value.state ?? value.phase),
    task: rawTask
      ? {
          id: stringValue(rawTask, "task_id", "id"),
          name: stringValue(rawTask, "task_name", "name") ?? "Current task",
          mode: normalizeTaskMode(stringValue(rawTask, "mode")),
          skillId: stringValue(rawTask, "skill_id"),
          skillRevision: numberValue(rawTask, "skill_revision", "revision"),
        }
      : stringValue(value, "task_name")
        ? {
            id: stringValue(value, "task_id"),
            name: stringValue(value, "task_name") ?? "Current task",
            mode: normalizeTaskMode(stringValue(value, "guidance_mode")) ?? normalizeTaskMode(stringValue(value, "mode")),
            skillId: stringValue(value, "skill_id"),
            skillRevision: numberValue(value, "skill_revision"),
          }
        : undefined,
    command: rawCommand
      ? {
          id: stringValue(rawCommand, "command_id", "id"),
          type: stringValue(rawCommand, "command_type", "type"),
          instruction: stringValue(rawCommand, "instruction"),
          safety: rawSafety
            ? {
                classification: (stringValue(rawSafety, "classification", "safety_classification") ?? "unknown") as "safe" | "money" | "identity" | "deletion" | "suspicious" | "unknown",
                title: stringValue(rawSafety, "title"),
                message: stringValue(rawSafety, "message"),
                actionDescription: stringValue(rawSafety, "irreversible_action", "action_description", "actionDescription"),
                amount: normalizeAmount(rawSafety.amount),
              }
            : undefined,
        }
      : undefined,
    liveViewUrl: stringValue(value, "live_view_url", "liveViewUrl"),
    syncState: stringValue(value, "sync_state") as SessionSnapshot["syncState"],
    guidanceMode: stringValue(value, "guidance_mode") === "none"
      ? "none"
      : normalizeGuidanceMode(stringValue(value, "guidance_mode")),
    outcomeMessage: stringValue(value, "terminal_message", "outcome_message", "message"),
    amount: rawAmount,
    completedAt: stringValue(value, "completed_at", "ended_at", "updated_at"),
    escalationId: stringValue(value, "escalation_id"),
    escalationDelivery: stringValue(value, "escalation_delivery", "delivery_status") as SessionSnapshot["escalationDelivery"],
    providerErrorCode: stringValue(value, "provider_error_code", "error_code"),
    providerMessage: stringValue(value, "provider_message", "error_message") ?? (
      phaseFrom(value.state ?? value.phase) === "provider_unavailable"
        ? stringValue(value, "terminal_message")
        : undefined
    ),
  };
}

function normalizeRoutine(value: unknown): Routine | undefined {
  if (!isRecord(value)) return undefined;
  const id = stringValue(value, "routine_id", "skill_id", "id");
  const name = stringValue(value, "task_name", "name", "title");
  if (!id || !name) return undefined;
  const skillId = stringValue(value, "skill_id");
  const source = stringValue(value, "source");
  const resolvedSkillId = skillId ?? (source === "everos" ? id : undefined);
  const startUrl = stringValue(value, "start_url");
  let startOrigin: string | undefined;
  if (startUrl) {
    try {
      startOrigin = new URL(startUrl).origin;
    } catch {
      startOrigin = undefined;
    }
  }
  return {
    id,
    name,
    description: stringValue(value, "description"),
    skillId: resolvedSkillId,
    revision: numberValue(value, "revision", "skill_revision"),
    startOrigin: startOrigin ?? stringValue(value, "start_origin", "origin"),
    lastCompletedAt: stringValue(value, "last_completed_at"),
    replayReady: booleanValue(value, "replay_ready") ?? Boolean(resolvedSkillId),
  };
}

function normalizeReminder(value: unknown): ProactiveReminder | undefined {
  if (!isRecord(value) || !isRecord(value.routine) || !isRecord(value.pattern)) return undefined;
  const id = stringValue(value, "id", "reminder_id");
  const reason = stringValue(value, "reason");
  const dueAt = stringValue(value, "due_at");
  const routine = normalizeRoutine(value.routine);
  const recurrence = stringValue(value.pattern, "recurrence");
  const typicalLocalTime = stringValue(value.pattern, "typical_local_time");
  const occurrenceCount = numberValue(value.pattern, "occurrence_count");
  if (!id || !reason || !dueAt || !routine || !typicalLocalTime || occurrenceCount === undefined) return undefined;
  if (recurrence !== "daily" && recurrence !== "weekly" && recurrence !== "monthly") return undefined;
  return {
    id,
    routine,
    reason,
    dueAt,
    recurrence,
    typicalLocalTime,
    occurrenceCount,
    overdueDays: numberValue(value, "overdue_days") ?? 0,
    permissionRequired: true,
  };
}

function normalizeReadiness(value: unknown): ReadinessSnapshot {
  if (!isRecord(value)) throw new ApiError("The readiness response was not valid.", 502, "invalid_response");
  const rawCapabilities = value.capabilities ?? value.providers;
  const capabilities: CapabilityReadiness[] = [];
  if (Array.isArray(rawCapabilities)) {
    for (const item of rawCapabilities) {
      if (!isRecord(item)) continue;
      capabilities.push({
        name: stringValue(item, "name", "provider") ?? "service",
        state: stringValue(item, "state"),
        configured: booleanValue(item, "configured") ?? false,
        reachable: booleanValue(item, "reachable") ?? false,
        authorized: booleanValue(item, "authorized") ?? false,
        lastCheckedAt: stringValue(item, "last_checked_at"),
        latencyMs: numberValue(item, "latency_ms"),
        errorCode: stringValue(item, "error_code"),
        detail: stringValue(item, "detail"),
      });
    }
  } else if (isRecord(rawCapabilities)) {
    for (const [name, item] of Object.entries(rawCapabilities)) {
      if (!isRecord(item)) continue;
      capabilities.push({
        name,
        state: stringValue(item, "state"),
        configured: booleanValue(item, "configured") ?? false,
        reachable: booleanValue(item, "reachable") ?? false,
        authorized: booleanValue(item, "authorized") ?? false,
        lastCheckedAt: stringValue(item, "last_checked_at"),
        latencyMs: numberValue(item, "latency_ms"),
        errorCode: stringValue(item, "error_code"),
        detail: stringValue(item, "detail"),
      });
    }
  }
  return {
    ready: booleanValue(value, "ready", "overall_ready") ?? false,
    mode: stringValue(value, "mode"),
    capabilities,
    checkedAt: stringValue(value, "checked_at", "last_checked_at"),
  };
}

class WebAccessibleApi {
  private accessToken?: string;

  setAccessToken(token?: string) {
    this.accessToken = token;
  }

  private headers(extra?: HeadersInit): Headers {
    const headers = new Headers(extra);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    if (this.accessToken) headers.set("Authorization", `Bearer ${this.accessToken}`);
    return headers;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = this.headers(init.headers);
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(requestUrl(path), {
      ...init,
      headers,
      credentials: "omit",
    });
    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const record = isRecord(payload) ? payload : undefined;
      const detail = record && isRecord(record.detail) ? record.detail : record;
      const message = detail
        ? stringValue(detail, "message", "detail", "error")
        : typeof payload === "string" && payload.trim()
          ? payload.trim()
          : undefined;
      throw new ApiError(message ?? `Request failed with status ${response.status}.`, response.status, detail ? stringValue(detail, "code", "error_code") : undefined);
    }
    return payload as T;
  }

  async readiness(): Promise<ReadinessSnapshot> {
    return normalizeReadiness(await this.request<unknown>("/ready"));
  }

  async createParticipantSession(input: ParticipantSessionInput): Promise<ParticipantContext> {
    const participantName = input.caregiver_name ?? (input.role === "participant" ? "WebAccessible user" : "Caregiver");
    const requestBody = {
      user_id: input.user_id,
      participant_name: participantName,
      role: input.role === "participant" ? "user" : "caregiver",
      reading_size: input.preferences?.reading_size === "larger" ? "largest" : "large",
      voice_enabled: input.preferences?.voice_enabled ?? false,
      caregiver_mobile: input.caregiver_mobile || undefined,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      activity_memory_enabled: input.preferences?.activity_memory_enabled ?? false,
      proactive_reminders_enabled: input.preferences?.proactive_reminders_enabled ?? false,
    };
    const value = await this.request<unknown>("/v1/participant-sessions", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(requestBody),
    });
    if (!isRecord(value)) throw new ApiError("The participant response was not valid.", 502, "invalid_response");
    const participantSessionId = stringValue(value, "participant_session_id", "id");
    const userId = stringValue(value, "user_id");
    if (!participantSessionId || !userId) throw new ApiError("The participant response was incomplete.", 502, "invalid_response");
    const context: ParticipantContext = {
      participantSessionId,
      userId,
      displayName: stringValue(value, "display_name", "participant_name", "caregiver_name") ?? input.caregiver_name ?? (input.role === "participant" ? "Participant" : "Caregiver"),
      role: stringValue(value, "role") === "caregiver" ? "caregiver" : "participant",
      accessToken: stringValue(value, "access_token", "token"),
      readingSize: input.preferences?.reading_size ?? "large",
      voiceEnabled: input.preferences?.voice_enabled ?? false,
      activityMemoryEnabled: input.preferences?.activity_memory_enabled ?? false,
      proactiveRemindersEnabled: input.preferences?.proactive_reminders_enabled ?? false,
    };
    this.setAccessToken(context.accessToken);
    return context;
  }

  async listRoutines(query?: string): Promise<Routine[]> {
    const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
    const payload = await this.request<unknown>(`/v1/routines${suffix}`);
    const items = Array.isArray(payload) ? payload : isRecord(payload) && Array.isArray(payload.routines) ? payload.routines : [];
    return items.map(normalizeRoutine).filter((item): item is Routine => Boolean(item));
  }

  async listReminders(): Promise<ProactiveReminder[]> {
    const payload = await this.request<unknown>("/v1/reminders");
    const items = isRecord(payload) && Array.isArray(payload.reminders) ? payload.reminders : [];
    return items.map(normalizeReminder).filter((item): item is ProactiveReminder => Boolean(item));
  }

  async dismissReminder(reminderId: string, snoozeMinutes = 1440): Promise<void> {
    await this.request<unknown>(`/v1/reminders/${encodeURIComponent(reminderId)}:dismiss`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ snooze_minutes: snoozeMinutes }),
    });
  }

  async acceptReminder(reminderId: string): Promise<SessionSnapshot> {
    const payload = await this.request<unknown>(`/v1/reminders/${encodeURIComponent(reminderId)}:accept`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    if (!isRecord(payload) || !payload.session) {
      throw new ApiError("The reminder did not create a task session.", 502, "invalid_response");
    }
    return normalizeSession(payload.session);
  }

  async resolveTasks(query: string): Promise<Routine[]> {
    const payload = await this.request<unknown>("/v1/tasks:resolve", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ query }),
    });
    const items = Array.isArray(payload)
      ? payload
      : isRecord(payload) && Array.isArray(payload.candidates)
        ? payload.candidates
        : isRecord(payload) && Array.isArray(payload.routines)
          ? payload.routines
          : [];
    return items.map(normalizeRoutine).filter((item): item is Routine => Boolean(item));
  }

  async createSession(input: SessionCreateInput): Promise<SessionSnapshot> {
    return normalizeSession(await this.request<unknown>("/v1/sessions", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(input),
    }));
  }

  async attachBrowser(sessionId: string): Promise<SessionSnapshot> {
    const value = await this.request<unknown>(`/v1/sessions/${encodeURIComponent(sessionId)}/browser`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    return normalizeSession(value);
  }

  async liveView(sessionId: string): Promise<string> {
    const payload = await this.request<unknown>(`/v1/sessions/${encodeURIComponent(sessionId)}/browser/live-view`);
    if (typeof payload === "string" && payload.length > 0) return payload;
    if (isRecord(payload)) {
      const url = stringValue(payload, "live_view_url", "url");
      if (url) return url;
    }
    throw new ApiError("Live View is not available for this session.", 502, "live_view_unavailable");
  }

  async getSession(sessionId: string): Promise<SessionSnapshot> {
    return normalizeSession(await this.request<unknown>(`/v1/sessions/${encodeURIComponent(sessionId)}`));
  }

  async startTask(taskId: string, participantSessionId: string, mode: "cold_teach" | "replay"): Promise<SessionSnapshot> {
    return normalizeSession(await this.request<unknown>(`/v1/tasks/${encodeURIComponent(taskId)}:start`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ mode, participant_session_id: participantSessionId }),
    }));
  }

  async endTask(sessionId: string, reason: string): Promise<void> {
    await this.request<unknown>(`/v1/tasks/${encodeURIComponent(sessionId)}:end`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ reason }),
    });
  }

  async stopBrowser(sessionId: string, reason: string): Promise<void> {
    void reason;
    await this.request<unknown>(`/v1/sessions/${encodeURIComponent(sessionId)}/browser:stop`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
  }

  async sendSessionEvent(snapshot: SessionSnapshot, event: SessionEventInput): Promise<SessionSnapshot> {
    if (!snapshot.userId || !snapshot.browserbaseSessionId || !snapshot.pageId || !snapshot.pageInstanceId || snapshot.nextSequenceNo === undefined || !snapshot.pageOrigin) {
      throw new ApiError("The browser page is not ready for this action yet.", 409, "page_context_unavailable");
    }
    const eventId = crypto.randomUUID();
    const envelope = {
      contract_version: "1.0",
      event_id: eventId,
      session_id: snapshot.id,
      user_id: snapshot.userId,
      browserbase_session_id: snapshot.browserbaseSessionId,
      page_id: snapshot.pageId,
      page_instance_id: snapshot.pageInstanceId,
      sequence_no: snapshot.nextSequenceNo,
      occurred_at: new Date().toISOString(),
      origin: snapshot.pageOrigin,
      redacted_path: snapshot.redactedPath ?? "/",
      event_type: event.eventType,
      payload: event.payload ?? {},
    };
    const payload = await this.request<unknown>(`/v1/sessions/${encodeURIComponent(snapshot.id)}/events:batch`, {
      method: "POST",
      headers: { "Idempotency-Key": eventId },
      body: JSON.stringify({ events: [envelope], expected_state_version: snapshot.stateVersion }),
    });
    const response = isRecord(payload) && isRecord(payload.session) ? payload.session : payload;
    const command = isRecord(payload) ? payload.command : undefined;
    return normalizeSession(response, command);
  }

  async requestHelp(snapshot: SessionSnapshot): Promise<SessionSnapshot> {
    const value = await this.request<unknown>(`/v1/sessions/${encodeURIComponent(snapshot.id)}:help`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    const session = isRecord(value) && isRecord(value.session) ? value.session : value;
    const command = isRecord(value) ? value.command : undefined;
    return normalizeSession(session, command);
  }

  async dismissHelp(snapshot: SessionSnapshot): Promise<SessionSnapshot> {
    const value = await this.request<unknown>(`/v1/sessions/${encodeURIComponent(snapshot.id)}:dismiss`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    const session = isRecord(value) && isRecord(value.session) ? value.session : value;
    const command = isRecord(value) ? value.command : undefined;
    return normalizeSession(session, command);
  }

  async getSkill(skillId: string): Promise<SkillDocument> {
    const value = await this.request<unknown>(`/v1/skills/${encodeURIComponent(skillId)}`);
    return normalizeSkill(value, skillId);
  }

  async reviseSkill(skillId: string, input: SkillRevisionInput): Promise<SkillDocument> {
    const value = await this.request<unknown>(`/v1/skills/${encodeURIComponent(skillId)}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
    return normalizeSkill(value, skillId);
  }

  async deleteSkill(skillId: string): Promise<void> {
    await this.request<unknown>(`/v1/skills/${encodeURIComponent(skillId)}`, {
      method: "DELETE",
    });
  }

  async uploadReviewedBill(document: File): Promise<ReviewedBillUpload> {
    const body = new FormData();
    body.append("document", document);
    body.append("reviewed", "true");
    const value = await this.request<unknown>("/v1/uploads", { method: "POST", body });
    if (!isRecord(value)) {
      throw new ApiError("The reviewed upload response was not valid.", 502, "invalid_response");
    }
    const objectKey = stringValue(value, "object_key");
    const indexingStatus = stringValue(value, "indexing_status");
    if (!objectKey || indexingStatus !== "awaiting_memory_add" || value.reviewed !== true) {
      throw new ApiError("The reviewed upload receipt was incomplete.", 502, "invalid_response");
    }
    return { objectKey, indexingStatus, reviewed: true };
  }

  async answerEpisode(query: string): Promise<EpisodeAnswer> {
    const value = await this.request<unknown>(`/v1/episodes:answer?query=${encodeURIComponent(query)}`);
    if (!isRecord(value)) throw new ApiError("The completion response was not valid.", 502, "invalid_response");
    return {
      found: booleanValue(value, "found") ?? Boolean(stringValue(value, "answer")),
      answer: stringValue(value, "answer"),
      taskName: stringValue(value, "task_name"),
      occurredAt: stringValue(value, "occurred_at", "completed_at"),
      amount: normalizeAmount(value.amount, value.currency),
      outcome: stringValue(value, "outcome") as EpisodeAnswer["outcome"],
    };
  }

  async caregiverDashboard(): Promise<{ history: CaregiverHistoryResponse; costs: CostRunsResponse; costError?: string }> {
    const value = await this.request<unknown>("/v1/caregivers/me/dashboard");
    if (!isRecord(value)) throw new ApiError("The caregiver dashboard response was not valid.", 502, "invalid_response");
    const rawSessions = Array.isArray(value.sessions) ? value.sessions : [];
    const rawEscalations = Array.isArray(value.escalations) ? value.escalations : [];
    const escalationBySession = new Map<string, JsonRecord>();
    for (const item of rawEscalations) {
      if (!isRecord(item)) continue;
      const sessionId = stringValue(item, "session_id");
      if (sessionId) escalationBySession.set(sessionId, item);
    }
    const sessions = rawSessions.flatMap((item) => {
      if (!isRecord(item)) return [];
      const id = stringValue(item, "id", "session_id");
      const startedAt = stringValue(item, "created_at", "started_at");
      if (!id || !startedAt) return [];
      const escalation = escalationBySession.get(id);
      const state = stringValue(item, "state", "outcome") ?? "unknown";
      const terminal = ["completed", "prepared", "escalated", "abandoned", "failed"].includes(state);
      return [{
        id,
        taskName: stringValue(item, "task_name") ?? "Task",
        participantName: stringValue(item, "participant_name"),
        startedAt,
        endedAt: terminal ? stringValue(item, "updated_at", "ended_at") : undefined,
        outcome: state,
        guidanceMode: stringValue(item, "guidance_mode", "mode"),
        syncState: stringValue(item, "sync_state"),
        escalationId: escalation ? stringValue(escalation, "id", "escalation_id") : undefined,
        noteCount: escalation && stringValue(escalation, "caregiver_note") ? 1 : 0,
      }];
    });
    const rawRuns = Array.isArray(value.cost_runs) ? value.cost_runs : [];
    const runs = rawRuns.flatMap((item) => {
      if (!isRecord(item)) return [];
      const runId = stringValue(item, "run_id", "id");
      if (!runId) return [];
      return [{
        runId,
        taskName: stringValue(item, "task_name") ?? "Task",
        runNumber: numberValue(item, "run_no", "run_number"),
        mode: stringValue(item, "run_kind", "guidance_mode", "mode") ?? "unknown",
        inputTokens: numberValue(item, "input_tokens"),
        outputTokens: numberValue(item, "output_tokens"),
        totalTokens: numberValue(item, "actual_model_tokens"),
        costUsd: numberValue(item, "actual_cost_usd", "cost_usd", "usd"),
        latencyMs: numberValue(item, "latency_ms"),
        occurredAt: stringValue(item, "occurred_at", "started_at"),
        synced: booleanValue(item, "synced") ?? (
          ["verified", "verified_zero"].includes(stringValue(item, "cost_status") ?? "") ||
          stringValue(item, "sync_state") === "synced"
        ),
      }];
    });
    const telemetry = isRecord(value.telemetry_status) ? value.telemetry_status : undefined;
    const telemetryReady = telemetry
      ? booleanValue(telemetry, "configured") && booleanValue(telemetry, "reachable") && booleanValue(telemetry, "authorized")
      : true;
    return {
      history: { sessions },
      costs: {
        runs,
        currency: stringValue(value, "currency") ?? "USD",
        source: stringValue(value, "cost_source", "source"),
      },
      costError: telemetryReady ? undefined : stringValue(telemetry ?? {}, "detail", "error_code") ?? "Snowflake cost records are unavailable.",
    };
  }

  async addCaregiverNote(escalationId: string, message: string, authorName: string): Promise<CaregiverNote> {
    const value = await this.request<unknown>(`/v1/escalations/${encodeURIComponent(escalationId)}/notes`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ text: message, author_name: authorName }),
    });
    if (!isRecord(value)) throw new ApiError("The note response was not valid.", 502, "invalid_response");
    return {
      id: stringValue(value, "note_id", "id") ?? crypto.randomUUID(),
      authorName: stringValue(value, "caregiver_name", "author_name") ?? authorName,
      message: stringValue(value, "caregiver_note", "message") ?? message,
      createdAt: stringValue(value, "updated_at", "created_at"),
      deliveryStatus: stringValue(value, "delivery_status", "status"),
    };
  }

  async streamSession(
    sessionId: string,
    signal: AbortSignal,
    onSnapshot: (snapshot: SessionSnapshot) => void,
    onCaregiverNote?: (note: CaregiverPanelNote) => void,
  ): Promise<void> {
    await this.consumeStream(
      `/v1/sessions/${encodeURIComponent(sessionId)}${STREAM_PATH}`,
      signal,
      (parsed) => {
        const eventType = isRecord(parsed) ? stringValue(parsed, "type") : undefined;
        if (eventType === "caregiver_note" && isRecord(parsed)) {
          const authorName = stringValue(parsed, "author_name");
          const noteText = stringValue(parsed, "text");
          if (authorName && noteText) onCaregiverNote?.({ authorName, text: noteText });
        } else if (eventType === "keepalive") {
          // Keep the stream open without replacing the current session snapshot.
        } else if (isRecord(parsed) && isRecord(parsed.session)) {
          onSnapshot(normalizeSession(parsed.session, parsed.command));
        } else if (isRecord(parsed) && stringValue(parsed, "id", "session_id")) {
          onSnapshot(normalizeSession(parsed));
        }
      },
    );
  }

  /**
   * Subscribe to participant-scoped notices for the whole visit.
   *
   * Proactive reminders have to arrive before any task session exists, so they come from
   * this stream rather than the session stream.
   */
  async streamParticipant(
    signal: AbortSignal,
    onReminder: (reminder: ProactiveReminder) => void,
  ): Promise<void> {
    await this.consumeStream("/v1/stream", signal, (parsed) => {
      if (!isRecord(parsed)) return;
      if (stringValue(parsed, "type") !== "proactive_reminder") return;
      const reminder = isRecord(parsed.reminder) ? normalizeReminder(parsed.reminder) : undefined;
      if (reminder) onReminder(reminder);
    });
  }

  private async consumeStream(
    path: string,
    signal: AbortSignal,
    onEvent: (parsed: unknown) => void,
  ): Promise<void> {
    const response = await fetch(requestUrl(path), {
      headers: this.headers({ Accept: "text/event-stream" }),
      credentials: "omit",
      signal,
    });
    if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
      throw new ApiError("Live updates are unavailable.", response.status || 503, "stream_unavailable");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer = `${buffer}${decoder.decode(value, { stream: true })}`.replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const eventBlock = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = eventBlock
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) onEvent(JSON.parse(data) as unknown);
        boundary = buffer.indexOf("\n\n");
      }
    }
  }
}

function renderSkillMarkdown(value: JsonRecord): string | undefined {
  const name = stringValue(value, "name");
  const startUrl = stringValue(value, "start_url");
  const steps = Array.isArray(value.steps) ? value.steps : undefined;
  if (!name || !startUrl || !steps) return undefined;
  const lines = [
    "---",
    `schema_version: ${numberValue(value, "schema_version") ?? 1}`,
    `skill_key: ${stringValue(value, "skill_key") ?? "not reported"}`,
    `revision: ${numberValue(value, "revision") ?? 1}`,
    `name: ${name}`,
    `start_url: ${startUrl}`,
    `task_outcome: ${stringValue(value, "task_outcome") ?? "not reported"}`,
    "---",
    "",
    `# ${name}`,
    "",
  ];
  for (const [index, rawStep] of steps.entries()) {
    if (!isRecord(rawStep)) continue;
    lines.push(`${index + 1}. ${stringValue(rawStep, "instruction") ?? "Instruction unavailable"}`);
  }
  return lines.join("\n");
}

function normalizeSkill(value: unknown, requestedId: string): SkillDocument {
  if (!isRecord(value)) {
    throw new ApiError("The skill response was not valid.", 502, "invalid_response");
  }
  const markdown = stringValue(value, "markdown", "content", "body") ?? renderSkillMarkdown(value);
  if (!markdown) throw new ApiError("This skill has no readable document.", 502, "invalid_response");
  const rawSteps = Array.isArray(value.steps) ? value.steps : [];
  const steps = rawSteps.flatMap((rawStep) => {
    if (!isRecord(rawStep)) return [];
    const id = stringValue(rawStep, "step_id", "id");
    const instruction = stringValue(rawStep, "instruction");
    return id && instruction ? [{ id, instruction }] : [];
  });
  return {
    id: stringValue(value, "skill_id", "id", "provider_skill_id") ?? requestedId,
    skillKey: stringValue(value, "skill_key"),
    name: stringValue(value, "name", "title") ?? "Saved routine",
    revision: numberValue(value, "revision"),
    markdown,
    steps,
    sourceSessionId: stringValue(value, "source_session_id"),
    outcome: stringValue(value, "task_outcome", "outcome"),
    updatedAt: stringValue(value, "updated_at", "created_at"),
  };
}

export const api = new WebAccessibleApi();
