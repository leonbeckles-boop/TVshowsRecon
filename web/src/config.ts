// web/src/config.ts
export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "https://whatnext-api.onrender.com/api";
