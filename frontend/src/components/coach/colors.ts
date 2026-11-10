import { SPORT_COLORS_HEX } from '../../constants/sportColors'
import { ACCENT } from '../garmin/garmin'

// The app's own identities: runs in the Run red, Garmin in its cyan, the race in its amber.
// Run red against Garmin cyan passes the dataviz palette check; Garmin is also drawn hollow.
export const RUN = SPORT_COLORS_HEX.Run
export const GARMIN_DARK = ACCENT
export const GARMIN_LIGHT = '#0891b2' // cyan-600: Garmin's cyan, dark enough for 3:1 on the light surface
export const GOAL = '#eab308'
