import { API_BASE } from "./apiBase.js";
import { parseResponseJson } from "./parseResponseJson.js";

export async function loginUser(email, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await parseResponseJson(res);
  if (!res.ok) throw new Error(data.detail || "Đăng nhập thất bại");
  return data;
}

export async function registerUser(username, email, password) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password }),
  });
  const data = await parseResponseJson(res);
  if (!res.ok) throw new Error(data.detail || "Đăng ký thất bại");
  return data;
}
