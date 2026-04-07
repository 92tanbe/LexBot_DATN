import { createContext, useContext, useState, useCallback } from "react";
import { loginUser, registerUser } from "../services/authService";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const stored = localStorage.getItem("lexbot_user");
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const [token, setToken] = useState(() => localStorage.getItem("lexbot_token") || null);

  const login = useCallback(async (email, password) => {
    const data = await loginUser(email, password);
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem("lexbot_token", data.access_token);
    localStorage.setItem("lexbot_user", JSON.stringify(data.user));
    return data;
  }, []);

  const register = useCallback(async (username, email, password) => {
    const data = await registerUser(username, email, password);
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem("lexbot_token", data.access_token);
    localStorage.setItem("lexbot_user", JSON.stringify(data.user));
    return data;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
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
