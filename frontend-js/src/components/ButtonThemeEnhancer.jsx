import { useEffect } from 'react';

const POSITIVE = /\b(approve|complete|receive|received|post|confirm|accept|restore access)\b/i;
const DESTRUCTIVE = /\b(reject|delete|revoke|deactivate|remove|permanently reset)\b/i;
const SECONDARY = /\b(view|cancel|close|back|clear|audit|history|preview)\b/i;
const PRIMARY = /\b(save|submit|create|add|new|edit|print|download|export|upload|issue|generate|update|sign in|change password)\b/i;

function applyRole(button) {
  if (!(button instanceof HTMLButtonElement) || button.closest('.app-sidebar') || button.closest('.topbar-account-menu') || button.closest('.topbar-search')) return;
  const label = `${button.getAttribute('aria-label') || ''} ${button.textContent || ''}`.replace(/\s+/g, ' ').trim();
  if (!label) return;
  button.classList.remove('pf-action-primary', 'pf-action-secondary', 'pf-action-positive', 'pf-action-destructive');
  const role = DESTRUCTIVE.test(label) ? 'destructive'
    : POSITIVE.test(label) ? 'positive'
    : SECONDARY.test(label) ? 'secondary'
    : PRIMARY.test(label) ? 'primary'
    : null;
  if (role) button.classList.add(`pf-action-${role}`);
}

export default function ButtonThemeEnhancer() {
  useEffect(() => {
    const update = root => {
      if (root instanceof HTMLButtonElement) applyRole(root);
      root.querySelectorAll?.('button').forEach(applyRole);
    };
    update(document);
    const observer = new MutationObserver(records => records.forEach(record => {
      if (record.type === 'characterData') applyRole(record.target.parentElement?.closest('button'));
      record.addedNodes.forEach(node => node.nodeType === Node.ELEMENT_NODE && update(node));
    }));
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, []);
  return null;
}
