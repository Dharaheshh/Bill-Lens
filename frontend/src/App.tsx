import { Routes, Route, Link } from 'react-router-dom'
import ResultDashboard from './pages/ResultDashboard'

function PlaceholderCard({ title }: { title: string }) {
  return (
    <div className="p-6 bg-surface border border-border rounded-cards shadow-sm m-4 text-text">
      <h2 className="text-xl font-bold mb-2">{title}</h2>
      <p className="text-muted">Placeholder for {title}</p>
    </div>
  )
}

function Stepper() {
  return (
    <div className="flex gap-4 p-4 border-b border-border bg-surface overflow-x-auto text-sm text-text">
      <Link to="/coverage" className="hover:text-accent">Coverage</Link>
      <Link to="/bill" className="hover:text-accent">Bill</Link>
      <Link to="/run/test" className="hover:text-accent">Analysis</Link>
      <Link to="/run/test/verify" className="hover:text-accent">Verify</Link>
      <Link to="/run/test/result" className="hover:text-accent">Result</Link>
      <Link to="/run/test/actions" className="hover:text-accent">Action</Link>
    </div>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-bg">
      <header className="p-4 border-b border-border bg-surface flex justify-between items-center text-text">
        <Link to="/" className="font-bold text-lg text-accent">BillLens</Link>
        <div>
          <span className="text-sm text-muted">Mode: Live/Replay</span>
        </div>
      </header>
      
      <Stepper />

      <main className="max-w-7xl mx-auto p-4">
        <Routes>
          <Route path="/" element={<PlaceholderCard title="Hero + Start" />} />
          <Route path="/coverage" element={<PlaceholderCard title="PolicyPicker & Terms" />} />
          <Route path="/bill" element={<PlaceholderCard title="BillDropzone" />} />
          <Route path="/run/mock/result" element={<ResultDashboard />} />
          <Route path="/run/:id" element={<PlaceholderCard title="TraceTimeline" />} />
          <Route path="/run/:id/verify" element={<PlaceholderCard title="LinesEditor (Verify)" />} />
          <Route path="/run/:id/result" element={<ResultDashboard />} />
          <Route path="/run/:id/actions" element={<PlaceholderCard title="Action Pack" />} />
        </Routes>
      </main>
    </div>
  )
}
