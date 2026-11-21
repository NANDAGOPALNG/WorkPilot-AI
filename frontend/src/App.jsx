import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import DashboardLayout from './components/layout/DashboardLayout'
import Assistant from './pages/Assistant'
import Documentation from './pages/Documentation'
import KnowledgeBase from './pages/KnowledgeBase'
import Tickets from './pages/Tickets'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<DashboardLayout />}>
          <Route index element={<Navigate to="/assistant" replace />} />
          <Route path="assistant" element={<Assistant />} />
          <Route path="knowledge" element={<KnowledgeBase />} />
          <Route path="tickets" element={<Tickets />} />
          <Route path="documentation" element={<Documentation />} />
          <Route path="*" element={<Navigate to="/assistant" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
