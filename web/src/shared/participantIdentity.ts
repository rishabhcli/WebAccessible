const PARTICIPANT_USER_ID_KEY = "webaccessible.participantUserId";

export function participantUserId(): string {
  const existing = window.localStorage.getItem(PARTICIPANT_USER_ID_KEY);
  if (existing && /^wa-[0-9a-f-]{36}$/.test(existing)) return existing;
  const created = `wa-${crypto.randomUUID()}`;
  window.localStorage.setItem(PARTICIPANT_USER_ID_KEY, created);
  return created;
}
