import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

react_coverage = '''
import React from 'react';
export default function Coverage() { return <div>Coverage</div>; }
'''
write_file("frontend/src/pages/Coverage.tsx", react_coverage)

react_billupload = '''
import React from 'react';
export default function BillUpload() { return <div>BillUpload</div>; }
'''
write_file("frontend/src/pages/BillUpload.tsx", react_billupload)

react_verifylines = '''
import React from 'react';
export default function VerifyLines() { return <div>VerifyLines</div>; }
'''
write_file("frontend/src/pages/VerifyLines.tsx", react_verifylines)

react_actionpack = '''
import React from 'react';
export default function ActionPack() { return <div>ActionPack</div>; }
'''
write_file("frontend/src/pages/ActionPack.tsx", react_actionpack)

react_runview = '''
import React from 'react';
export default function RunView() { return <div>RunView</div>; }
'''
write_file("frontend/src/pages/RunView.tsx", react_runview)

react_resultdashboard = '''
import React from 'react';
export default function ResultDashboard() { return <div>ResultDashboard</div>; }
'''
write_file("frontend/src/pages/ResultDashboard.tsx", react_resultdashboard)

react_app = '''
import React from 'react';
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
'''
write_file("frontend/src/App.tsx", react_app)
