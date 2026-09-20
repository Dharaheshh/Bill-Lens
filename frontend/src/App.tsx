import { Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import Coverage from './pages/Coverage';
import BillUpload from './pages/BillUpload';
import VerifyLines from './pages/VerifyLines';
import ActionPack from './pages/ActionPack';
import RunView from './pages/RunView';
import ResultDashboard from './pages/ResultDashboard';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/coverage" element={<Coverage />} />
      <Route path="/upload" element={<BillUpload />} />
      <Route path="/verify" element={<VerifyLines />} />
      <Route path="/action" element={<ActionPack />} />
      <Route path="/run/:id" element={<RunView />} />
      <Route path="/result" element={<ResultDashboard />} />
    </Routes>
  );
}

export default App;
