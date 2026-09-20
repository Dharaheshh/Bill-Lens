import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createDemoRun, uploadPolicy, uploadBill, createRun } from '../api/client';

export default function Home() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [policyFile, setPolicyFile] = useState<File | null>(null);
  const [billFile, setBillFile] = useState<File | null>(null);

  const startDemo = async (sampleId: string) => {
    setLoading(true);
    try {
      const res = await createDemoRun(sampleId);
      navigate(`/run/${res.run_id}`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const startCustom = async () => {
    if (!billFile) {
      setError("Bill file is required for live mode.");
      return;
    }
    setLoading(true);
    try {
      let pid = undefined;
      if (policyFile) {
        const pres = await uploadPolicy(policyFile);
        pid = pres.policy_id;
        // In full app, we'd wait for policy ingest. For now, create run directly.
      }
      const bres = await uploadBill(billFile);
      const rres = await createRun(bres.bill_id, pid, true); // autoConfirm=true for simplicity in this MVP
      navigate(`/run/${rres.run_id}`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <h1 className="text-3xl font-bold">Welcome to BillLens</h1>
      <p className="text-lg text-muted">Agentic Hospital Bill & Claim Auditor</p>
      
      {error && <div className="p-4 bg-red-100 text-red-700 rounded">{error}</div>}

      <div className="grid md:grid-cols-2 gap-8">
        <div className="p-6 border rounded-cards bg-surface shadow">
          <h2 className="text-xl font-bold mb-4">Try a Demo (Replay)</h2>
          <div className="space-y-4">
            <button disabled={loading} onClick={() => startDemo('sample-a-ortho-insured')} className="w-full text-left p-4 bg-bg hover:bg-gray-100 rounded border">
              <div className="font-bold">Sample A: Orthopedic Surgery</div>
              <div className="text-sm text-muted">Standard room, multiple deductions</div>
            </button>
            <button disabled={loading} onClick={() => startDemo('sample-b-pctsi-insured')} className="w-full text-left p-4 bg-bg hover:bg-gray-100 rounded border">
              <div className="font-bold">Sample B: Fever & Observation</div>
              <div className="text-sm text-muted">% SI room cap</div>
            </button>
          </div>
        </div>

        <div className="p-6 border rounded-cards bg-surface shadow">
          <h2 className="text-xl font-bold mb-4">Live Analysis</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Upload Policy PDF (Optional)</label>
              <input type="file" accept="application/pdf" onChange={e => setPolicyFile(e.target.files?.[0] || null)} className="w-full p-2 border rounded" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Upload Bill Image/PDF</label>
              <input type="file" accept="image/*,application/pdf" onChange={e => setBillFile(e.target.files?.[0] || null)} className="w-full p-2 border rounded" />
            </div>
            <button disabled={loading} onClick={startCustom} className="w-full py-2 bg-accent text-white font-bold rounded hover:opacity-90 transition">
              {loading ? 'Starting...' : 'Run Audit'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
