import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from './hooks/ThemeProvider'
import { ToastProvider } from './hooks/ToastProvider'
import { BackdropProvider } from './hooks/BackdropProvider'
import AppShell from './components/layout/AppShell'
import RootErrorBoundary from './components/layout/RootErrorBoundary'
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
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const GarminPage = lazy(() => import('./pages/GarminPage'))
const CoveragePage = lazy(() => import('./pages/CoveragePage'))

function RouteFallback() {
  return (
    <div className="flex items-center justify-center py-16 text-gray-400">
      <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

export default function App() {
  return (
    <RootErrorBoundary>
      <ThemeProvider>
        <ToastProvider>
          <BackdropProvider>
            <AppShell>
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  <Route path="/" element={<Navigate to="/calendar" replace />} />
                  <Route path="/dashboard" element={<DashboardPage />} />
                  <Route path="/activities" element={<ActivitiesPage />} />
                  <Route path="/activities/:id" element={<ActivityDetailPage />} />
                  <Route path="/aggregations" element={<AggregationsPage />} />
                  <Route path="/coverage" element={<CoveragePage />} />
                  <Route path="/calendar" element={<CalendarPage />} />
                  <Route path="/records" element={<PersonalRecordsPage />} />
                  <Route path="/workouts" element={<WorkoutsPage />} />
                  <Route path="/races" element={<RacesPage />} />
                  <Route path="/analytics" element={<AnalyticsPage />} />
                  <Route path="/garmin" element={<GarminPage />} />
                  <Route path="/profile" element={<ProfilePage />} />
                </Routes>
              </Suspense>
            </AppShell>
          </BackdropProvider>
        </ToastProvider>
      </ThemeProvider>
    </RootErrorBoundary>
  )
}
