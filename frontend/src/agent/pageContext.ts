/** What the user is looking at, in words the agent reads with every message. */
export function pageContext(pathname: string, search: string): string {
  const params = new URLSearchParams(search)
  const [, page, id] = pathname.split('/')
  switch (page) {
    case 'coach': return id ? `the Coach page, plan ${id}` : 'the Coach page'
    case 'calendar': return 'the training calendar'
    case 'activities': return id ? `activity ${id}` : 'the activity list'
    case 'races': return 'the race calendar'
    case 'workouts': return 'the workout library'
    case 'analytics': return 'Analytics: fitness, form and race predictions'
    case 'records': return 'personal records'
    case 'garmin': return params.get('day') ? `Garmin wellness, the day ${params.get('day')}` : 'Garmin wellness'
    case 'coverage': return 'street coverage'
    case 'profile': return 'the profile'
    case 'gear': return id ? `gear ${id}` : 'gear'
    default: return pathname
  }
}
