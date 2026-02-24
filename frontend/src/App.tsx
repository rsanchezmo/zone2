import { Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from './hooks/useTheme'
import AppShell from './components/layout/AppShell'
import DashboardPage from './pages/DashboardPage'
import ActivitiesPage from './pages/ActivitiesPage'
import ActivityDetailPage from './pages/ActivityDetailPage'
import AggregationsPage from './pages/AggregationsPage'
import CalendarPage from './pages/CalendarPage'
import ProfilePage from './pages/ProfilePage'
import PersonalRecordsPage from './pages/PersonalRecordsPage'
import WorkoutsPage from './pages/WorkoutsPage'

export default function App() {
  return (
    <ThemeProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/calendar" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/activities" element={<ActivitiesPage />} />
          <Route path="/activities/:id" element={<ActivityDetailPage />} />
          <Route path="/aggregations" element={<AggregationsPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/records" element={<PersonalRecordsPage />} />
          <Route path="/workouts" element={<WorkoutsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Routes>
      </AppShell>
    </ThemeProvider>
  )
}
