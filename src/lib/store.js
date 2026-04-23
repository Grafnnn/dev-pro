import { seedData } from '../data/seed';

export const STORAGE_KEY = 'devland_codex_ready_v1';

export function uid(prefix) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

export function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(seedData));
      return structuredClone(seedData);
    }
    return JSON.parse(raw);
  } catch {
    return structuredClone(seedData);
  }
}

export function saveState(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function resetState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(seedData));
  return structuredClone(seedData);
}
