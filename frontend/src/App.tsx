import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from './hooks/useTheme'
import { ToastProvider } from './hooks/useToast'
import AppShell from './components/layout/AppShell'
import CalendarPage from './pages/CalendarPage'

// CalendarPage stays eager — it's the landing route, so making it lazy would
// add a Suspense flash on cold load. Everything else is lazy so its page
// chunk (and any page-unique deps) are downloaded on navigation.
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ActivitiesPage = lazy(() => import('./pages/ActivitiesPage'))
const ActivityDetailPage = lazy(() => import('./pages/ActivityDetailPage'))
const AggregationsPage = lazy(() => import('./pages/AggregationsPage'))
const PersonalRecordsPage = lazy(() => import('./pages/PersonalRecordsPage'))
const WorkoutsPage = lazy(() => import('./pages/WorkoutsPage'))
const RacesPage = lazy(() => import('./pages/RacesPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))

function RouteFallback() {
  return (
    <div className="flex items-center justify-center py-16 text-gray-400">
      <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AppShell>
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/" element={<Navigate to="/calendar" replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/activities" element={<ActivitiesPage />} />
              <Route path="/activities/:id" element={<ActivityDetailPage />} />
              <Route path="/aggregations" element={<AggregationsPage />} />
              <Route path="/calendar" element={<CalendarPage />} />
              <Route path="/records" element={<PersonalRecordsPage />} />
              <Route path="/workouts" element={<WorkoutsPage />} />
              <Route path="/races" element={<RacesPage />} />
              <Route path="/profile" element={<ProfilePage />} />
            </Routes>
          </Suspense>
        </AppShell>
      </ToastProvider>
    </ThemeProvider>
  )
}
