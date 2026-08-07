from __future__ import annotations

HIGHLIGHT_SCRIPT = r"""
(candidateId) => {
  document.querySelectorAll('[data-webaccessible-active="true"]').forEach((element) => {
    element.removeAttribute('data-webaccessible-active');
    element.style.removeProperty('outline');
    element.style.removeProperty('outline-offset');
    element.style.removeProperty('box-shadow');
    element.style.removeProperty('scroll-margin');
  });
  const escaped = CSS.escape(candidateId);
  const element = document.querySelector(`[data-webaccessible-candidate="${escaped}"]`);
  if (!element) return false;
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden') return false;
  if (element.disabled || element.getAttribute('aria-disabled') === 'true') return false;
  element.setAttribute('data-webaccessible-active', 'true');
  element.style.setProperty('outline', '5px solid #e64b38', 'important');
  element.style.setProperty('outline-offset', '5px', 'important');
  element.style.setProperty('box-shadow', '0 0 0 10px rgba(230,75,56,.22)', 'important');
  element.style.setProperty('scroll-margin', '120px', 'important');
  element.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'nearest'});
  return true;
}
"""


CLEAR_HIGHLIGHT_SCRIPT = r"""
() => {
  document.querySelectorAll('[data-webaccessible-active="true"]').forEach((element) => {
    element.removeAttribute('data-webaccessible-active');
    element.style.removeProperty('outline');
    element.style.removeProperty('outline-offset');
    element.style.removeProperty('box-shadow');
    element.style.removeProperty('scroll-margin');
  });
}
"""
