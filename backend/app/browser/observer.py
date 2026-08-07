from __future__ import annotations

INSTALL_OBSERVER_SCRIPT = r"""
() => {
  if (window.__webaccessibleObserverInstalled) return;
  window.__webaccessibleObserverInstalled = true;
  let lastScrollY = window.scrollY;
  let scrollTimer = null;
  const candidateId = (target) => target instanceof Element
    ? target.closest('[data-webaccessible-candidate]')?.getAttribute('data-webaccessible-candidate') || null
    : null;
  const send = (payload) => {
    try { window.__webaccessibleEmit(payload); } catch (_) { /* bridge disconnected */ }
  };
  document.addEventListener('click', (event) => {
    if (!event.isTrusted) return;
    send({kind: 'activation', source: 'pointer', trusted: true, candidate_id: candidateId(event.target)});
  }, true);
  document.addEventListener('keydown', (event) => {
    if (!event.isTrusted || !['Enter', ' '].includes(event.key)) return;
    send({kind: 'activation', source: 'keyboard', trusted: true, candidate_id: candidateId(event.target)});
  }, true);
  document.addEventListener('input', (event) => {
    if (!event.isTrusted || !(event.target instanceof Element)) return;
    const type = (event.target.getAttribute('type') || '').toLowerCase();
    const metadata = [event.target.getAttribute('name'), event.target.getAttribute('autocomplete')]
      .filter(Boolean).join(' ').toLowerCase();
    if (type === 'password' || /card|cvv|cvc|ssn|social.security|bank|routing|token/.test(metadata)) return;
    send({kind: 'form_progress', trusted: true, candidate_id: candidateId(event.target), dirty: true});
  }, true);
  window.addEventListener('scroll', () => {
    if (scrollTimer) return;
    scrollTimer = setTimeout(() => {
      const viewport = Math.max(window.innerHeight, 1);
      const delta = Math.abs(window.scrollY - lastScrollY) / viewport;
      lastScrollY = window.scrollY;
      scrollTimer = null;
      send({kind: 'scroll', trusted: true, viewport_delta: delta});
    }, 200);
  }, {passive: true});
  window.setInterval(() => send({kind: 'heartbeat', trusted: true}), 5000);
}
"""
