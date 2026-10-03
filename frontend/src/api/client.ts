import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
});

/** The API's own message for a failed request (FastAPI's `detail`), else the fallback. */
export function errorDetail(error: unknown, fallback: string): string {
  const detail = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
  return typeof detail === 'string' ? detail : fallback;
}

export default api;
