const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function fetchApi(path: string, options?: RequestInit) {
  const res = await fetch(`${API_URL}${path}`, options);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function uploadPolicy(file: File) {
  const fd = new FormData();
  fd.append('file', file);
  return fetchApi('/policies', { method: 'POST', body: fd });
}

export async function uploadBill(file: File) {
  const fd = new FormData();
  fd.append('file', file);
  return fetchApi('/bills', { method: 'POST', body: fd });
}

export async function createRun(billId: string, policyId?: string, autoConfirm = false) {
  return fetchApi('/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bill_id: billId, policy_id: policyId, auto_confirm: autoConfirm })
  });
}

export async function createDemoRun(sampleId: string) {
  return fetchApi(`/demo/${sampleId}`, { method: 'POST' });
}

export async function getRunResult(runId: string) {
  return fetchApi(`/runs/${runId}/result`);
}

export async function confirmRun(runId: string, lines: any[], isInsured: boolean, policyId?: string) {
  return fetchApi(`/runs/${runId}/confirm`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lines, is_insured: isInsured, policy_id: policyId })
  });
}
