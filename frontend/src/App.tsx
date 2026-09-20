
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Coverage from './pages/Coverage';
import BillUpload from './pages/BillUpload';
import VerifyLines from './pages/VerifyLines';
import ActionPack from './pages/ActionPack';
import RunView from './pages/RunView';
import ResultDashboard from './pages/ResultDashboard';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Coverage />} />
        <Route path="/upload" element={<BillUpload />} />
        <Route path="/verify" element={<VerifyLines />} />
        <Route path="/action" element={<ActionPack />} />
        <Route path="/run" element={<RunView />} />
        <Route path="/result" element={<ResultDashboard />} />
      </Routes>
    </BrowserRouter>
  );
}
export default App;
