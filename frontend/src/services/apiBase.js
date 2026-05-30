/** Base URL API LexBot: dev không set env -> relative URL + proxy Vite (xem vite.config.js). */

function trimTrailingSlash(s) {
  return s.replace(/\/+$/, "");
}

const raw = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE;

export const API_BASE =
  typeof raw === "string" && raw.trim() !== ""
    ? trimTrailingSlash(raw.trim())
    : import.meta.env.DEV
      ? ""
      : trimTrailingSlash("http://localhost:8000");
