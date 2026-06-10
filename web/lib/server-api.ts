export const SERVER_API_BASE =
  process.env.GAMETIME_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000";
