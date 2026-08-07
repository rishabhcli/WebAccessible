from __future__ import annotations

EXTRACT_CANDIDATES_SCRIPT = r"""
() => {
  const MAX_CANDIDATES = 120;
  const MAX_TEXT = 180;
  const allowedTags = new Set(['a','button','input','select','textarea','summary','option','label','div','span']);
  const interactive = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary',
    '[role="button"]', '[role="link"]', '[role="checkbox"]', '[role="radio"]',
    '[role="tab"]', '[role="menuitem"]', '[role="switch"]', '[tabindex]'
  ].join(',');
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT);
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const implicitRole = (element) => {
    const tag = element.tagName.toLowerCase();
    const type = (element.getAttribute('type') || '').toLowerCase();
    if (tag === 'a' && element.hasAttribute('href')) return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input' && ['checkbox','radio','button','submit','reset'].includes(type)) return type === 'submit' ? 'button' : type;
    if (tag === 'input') return 'textbox';
    return null;
  };
  const accessibleName = (element) => {
    const aria = element.getAttribute('aria-label');
    if (aria) return normalize(aria);
    const labelledBy = element.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ');
      if (normalize(text)) return normalize(text);
    }
    if (element.id) {
      const escaped = CSS.escape(element.id);
      const label = document.querySelector(`label[for="${escaped}"]`);
      if (label) return normalize(label.textContent);
    }
    return normalize(element.innerText || element.textContent || element.getAttribute('title'));
  };
  const sensitivity = (element) => {
    const type = (element.getAttribute('type') || '').toLowerCase();
    const metadata = [element.getAttribute('name'), element.getAttribute('id'), element.getAttribute('autocomplete'), element.getAttribute('aria-label')]
      .filter(Boolean).join(' ').toLowerCase();
    const flags = [];
    if (type === 'password') flags.push('password');
    if (type === 'hidden') flags.push('hidden');
    if (/card|cvv|cvc|payment|credit/.test(metadata)) flags.push('payment');
    if (/ssn|social.security|passport|identity|tax.id/.test(metadata)) flags.push('identity');
    if (/bank|routing|account.number/.test(metadata)) flags.push('bank');
    if (/token|secret/.test(metadata)) flags.push('token');
    return [...new Set(flags)];
  };
  const checkedState = (element) => {
    const ariaChecked = element.getAttribute('aria-checked');
    if (ariaChecked === 'true') return true;
    if (ariaChecked === 'false') return false;
    if (element instanceof HTMLInputElement && ['checkbox', 'radio'].includes(element.type)) {
      return element.checked;
    }
    return null;
  };
  const cssPath = (element) => {
    if (element.id && !/[0-9a-f]{8,}/i.test(element.id)) return `#${CSS.escape(element.id)}`;
    const stable = ['data-testid','data-test','name'];
    for (const attribute of stable) {
      const value = element.getAttribute(attribute);
      if (value && value.length < 80) return `${element.tagName.toLowerCase()}[${attribute}="${CSS.escape(value)}"]`;
    }
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && parts.length < 5) {
      let part = current.tagName.toLowerCase();
      const parent = current.parentElement;
      if (parent) {
        const siblings = [...parent.children].filter(child => child.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(' > ');
  };
  const makeId = (element, index) => {
    let id = element.getAttribute('data-webaccessible-candidate');
    if (!id) {
      id = `wa-${Date.now().toString(36)}-${index.toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
      element.setAttribute('data-webaccessible-candidate', id);
    }
    return id;
  };
  return [...document.querySelectorAll(interactive)].filter(visible).slice(0, MAX_CANDIDATES).map((element, index) => {
    const rect = element.getBoundingClientRect();
    const href = element instanceof HTMLAnchorElement && element.href ? new URL(element.href) : null;
    const tag = allowedTags.has(element.tagName.toLowerCase()) ? element.tagName.toLowerCase() : 'div';
    return {
      candidate: {
        candidate_id: makeId(element, index),
        role: element.getAttribute('role') || implicitRole(element),
        accessible_name: accessibleName(element) || null,
        visible_text: normalize(element.innerText || element.textContent) || null,
        tag_name: tag,
        input_type: element instanceof HTMLInputElement ? (element.type || 'text').slice(0, 32) : null,
        visible: true,
        enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
        focusable: element.tabIndex >= 0,
        checked: checkedState(element),
        bounding_rect: {
          x: Math.round(rect.x), y: Math.round(rect.y),
          width: Math.round(rect.width), height: Math.round(rect.height)
        },
        href_origin: href ? href.origin : null,
        href_redacted_path: href ? href.pathname : null,
        sensitivity_flags: sensitivity(element)
      },
      css_path: cssPath(element)
    };
  });
}
"""


SINGLE_CANDIDATE_SCRIPT = r"""
(element) => {
  if (!(element instanceof Element)) return null;
  const id = element.closest('[data-webaccessible-candidate]')?.getAttribute('data-webaccessible-candidate');
  return id || null;
}
"""
