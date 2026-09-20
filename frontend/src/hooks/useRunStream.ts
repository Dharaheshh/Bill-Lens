import { useEffect, useState } from 'react';

export function useRunStream(runId: string | null) {
  const [events, setEvents] = useState<any[]>([]);
  const [status, setStatus] = useState<string>('idle');
  
  useEffect(() => {
    if (!runId) return;
    
    // reset
    setEvents([]);
    setStatus('connecting');
    
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const source = new EventSource(`${apiUrl}/runs/${runId}/stream`);
    
    source.onopen = () => setStatus('connected');
    
    source.onmessage = (e) => {
      if (e.data === 'ping') return;
      try {
        const data = JSON.parse(e.data);
        setEvents(prev => {
          const exists = prev.find(ev => ev.id === e.lastEventId);
          if (exists) return prev;
          return [...prev, { ...data, id: e.lastEventId }];
        });
      } catch (err) {
        console.error('SSE parse error', err);
      }
    };
    
    source.onerror = () => {
      setStatus('error');
      source.close();
    };
    
    return () => source.close();
  }, [runId]);
  
  return { events, status };
}
