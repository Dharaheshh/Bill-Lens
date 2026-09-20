import { useEffect, useState } from 'react'

export default function ResultDashboard() {
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    fetch('/src/mocks/run-a.json')
      .then(res => res.json())
      .then(d => setData(d))
  }, [])

  if (!data) return <div>Loading...</div>

  return (
    <div className="flex flex-col lg:flex-row gap-6 text-text">
      <div className="flex-1 bg-surface p-6 rounded-cards border border-border shadow-sm">
        <h2 className="text-xl font-bold mb-4 text-accent">Audit Table</h2>
        {data.findings.map((f: any) => (
          <div key={f.id} className="p-4 mb-2 bg-info-bg text-info rounded-controls border border-border">
            <strong>{f.title}</strong>: {f.explanation} (Amount at stake: ₹{f.amount_at_stake})
          </div>
        ))}
      </div>
      <div className="w-full lg:w-1/3 space-y-6">
        <div className="bg-surface p-6 rounded-cards border border-border shadow-sm">
          <h2 className="text-lg font-bold mb-2">Summary</h2>
          <div className="text-sm">
            <p>Billed Total: ₹{data.summary.billed_total}</p>
            <p className="text-amber">Questionable: ₹{data.summary.questionable_total}</p>
            <p className="text-red">Insurer Deductions: ₹{data.summary.insurer_deductions_total}</p>
            <p className="font-bold mt-2">Insurer likely pays: ₹{data.summary.insurer_pays}</p>
            <p className="font-bold text-accent">You pay: ₹{data.summary.patient_pays}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
