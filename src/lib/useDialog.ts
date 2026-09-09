import { useLayoutEffect, useMemo, useRef } from "react";

const stack: HTMLElement[] = [];
const inertOwners = new Map<HTMLElement, { count: number; original: boolean }>();
const focusable = 'a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])';

/** Contain keyboard focus, isolate the background, and return to the opener. */
export function useDialog<T extends HTMLElement = HTMLElement>(active: boolean, onClose: () => void) {
  const ref = useRef<T>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const opener = useMemo(() => active ? document.activeElement as HTMLElement | null : null, [active]);
  useLayoutEffect(() => {
    const root = ref.current;
    if (!active || !root) return;
    stack.push(root);
    const isolated: HTMLElement[] = [];
    for (let node: HTMLElement | null = root; node?.parentElement && node.parentElement !== document.documentElement; node = node.parentElement) {
      for (const sibling of node.parentElement.children) {
        if (sibling === node || !(sibling instanceof HTMLElement) || sibling.hasAttribute("data-dialog-backdrop") || /^(SCRIPT|STYLE|LINK)$/.test(sibling.tagName)) continue;
        const state = inertOwners.get(sibling) ?? { count: 0, original: sibling.hasAttribute("inert") };
        state.count++; inertOwners.set(sibling, state);
        sibling.setAttribute("inert", ""); isolated.push(sibling);
      }
    }
    const targets = () => [...root.querySelectorAll<HTMLElement>(focusable)].filter(item =>
      item.tabIndex >= 0 && !item.closest('[hidden],[inert],[aria-hidden="true"]') &&
      (typeof item.checkVisibility === "function" ? item.checkVisibility({ checkVisibilityCSS: true }) : getComputedStyle(item).display !== "none" && getComputedStyle(item).visibility !== "hidden"),
    );
    const focusFirst = () => (targets()[0] ?? root).focus({ preventScroll: true });
    if (!root.contains(document.activeElement)) focusFirst();
    function keydown(event: KeyboardEvent) {
      if (stack.at(-1) !== root || event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault(); event.stopPropagation(); close.current();
      } else if (event.key === "Tab") {
        const items = targets();
        const first = items[0] ?? root, last = items.at(-1) ?? root;
        if (event.shiftKey && (document.activeElement === first || document.activeElement === root)) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === root)) {
          event.preventDefault(); first.focus();
        }
      }
    }
    function focusin(event: FocusEvent) {
      if (stack.at(-1) === root && !root.contains(event.target as Node)) focusFirst();
    }
    document.addEventListener("keydown", keydown);
    document.addEventListener("focusin", focusin);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.removeEventListener("focusin", focusin);
      stack.splice(stack.indexOf(root), 1);
      for (const item of isolated) {
        const state = inertOwners.get(item)!;
        if (--state.count === 0) {
          if (!state.original) item.removeAttribute("inert");
          inertOwners.delete(item);
        }
      }
      const canRestore = opener?.isConnected && !opener.closest("[inert]") &&
        (typeof opener.checkVisibility !== "function" || opener.checkVisibility({ checkVisibilityCSS: true }));
      if (canRestore) opener.focus({ preventScroll: true });
      else if (root.id) document.querySelector<HTMLElement>(`[aria-controls="${root.id}"]`)?.focus({ preventScroll: true });
    };
  }, [active, opener]);
  return ref;
}
