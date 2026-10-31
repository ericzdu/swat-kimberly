import { HashRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import FieldBar from './components/FieldBar';
import { FieldProvider } from './context/FieldContext';
import Dashboard from './pages/Dashboard';
import Chat from './pages/Chat';
import GIS from './pages/GIS';
import Visualizations from './pages/Visualizations';
import FarmManagement from './pages/FarmManagement';
import SetupWizard from './pages/SetupWizard';
import DataHub from './pages/DataHub';
import Settings from './pages/Settings';
import SwatEditor from './pages/SwatEditor';

export default function App() {
  return (
    <HashRouter>
      <FieldProvider>
      <div className="flex h-screen bg-[var(--se-bg)] text-[var(--se-text)]">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <FieldBar />
          <main className="flex-1 overflow-y-auto min-h-0">
          <Routes>
            {/* Chat-native shell: three surfaces */}
            <Route path="/" element={<Chat />} />
            <Route path="/editor" element={<SwatEditor />} />
            <Route path="/settings" element={<Settings />} />

            {/* Retained (not in nav) for internal deep-links until P5 cleanup */}
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/setup" element={<SetupWizard />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/gis" element={<GIS />} />
            <Route path="/visualizations" element={<Visualizations />} />
            <Route path="/farms" element={<FarmManagement />} />
            <Route path="/data" element={<DataHub />} />
          </Routes>
          </main>
        </div>
      </div>
      </FieldProvider>
    </HashRouter>
  );
}
