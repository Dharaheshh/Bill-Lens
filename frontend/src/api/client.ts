const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function getSessionId() {
  let id = localStorage.getItem('X-Session-Id');
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem('X-Session-Id', id);
  }
  return id;
}

export async function apiClient(endpoint: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set('X-Session-Id', getSessionId());
  
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`);
  }
  
  if (response.status === 204) return null;
  return response.json();
}
