import { createContext, useContext, useState, useCallback } from "react";
import { loginUser, registerUser } from "../services/authService";

const AuthContext = createContext(null);

function decodeJwtPayload(token) {
  try {
    const [, payload] = String(token || "").split(".");
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(
      normalized.length + ((4 - (normalized.length % 4)) % 4),
      "="
    );
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

function isExpiredToken(token) {
  const payload = decodeJwtPayload(token);
  if (!payload || typeof payload.exp !== "number") return true;
  return payload.exp * 1000 <= Date.now();
}

function loadStoredAuth() {
  const token = localStorage.getItem("lexbot_token") || null;
  if (!token || isExpiredToken(token)) {
    localStorage.removeItem("lexbot_token");
    localStorage.removeItem("lexbot_user");
    return { token: null, user: null };
  }
  try {
    const stored = localStorage.getItem("lexbot_user");
    return { token, user: stored ? JSON.parse(stored) : null };
  } catch {
    localStorage.removeItem("lexbot_token");
    localStorage.removeItem("lexbot_user");
    return { token: null, user: null };
  }
}

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(loadStoredAuth);
  const user = auth.user;
  const token = auth.token;

  const login = useCallback(async (email, password) => {
    const data = await loginUser(email, password);
    setAuth({ token: data.access_token, user: data.user });
    localStorage.setItem("lexbot_token", data.access_token);
    localStorage.setItem("lexbot_user", JSON.stringify(data.user));
    return data;
  }, []);

  const register = useCallback(async (username, email, password) => {
    const data = await registerUser(username, email, password);
    setAuth({ token: data.access_token, user: data.user });
    localStorage.setItem("lexbot_token", data.access_token);
    localStorage.setItem("lexbot_user", JSON.stringify(data.user));
    return data;
  }, []);

  const logout = useCallback(() => {
    setAuth({ token: null, user: null });
    localStorage.removeItem("lexbot_token");
    localStorage.removeItem("lexbot_user");
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth phải được dùng trong AuthProvider");
  return ctx;
}
