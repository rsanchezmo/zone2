from strava.strava_activities_cache import StravaActivitiesCache
from strava.strava_user_cache import StravaUserCache
from strava.strava_utils import vo2_max


class StravaAnalytics:
    def __init__(self, strava_activities_cache: StravaActivitiesCache, strava_user_cache: StravaUserCache):
        self.strava_activities_cache = strava_activities_cache # inmutable data (historical activities)
        self.strava_user_cache = strava_user_cache # mutable data (user profile, stats, zones)


    """
    ===============
    USER ANALYTICS
    ===============
    """

    def get_rest_heart_rate(self):
        """Get the athlete's resting heart rate from cached zones estimated as Z2_min / 2 as proxy."""
        zones = self.strava_user_cache.get_athlete_zones()
        hr_rest = zones['heart_rate']['zones'][1]['min'] / 2

        if hr_rest == 0:
            hr_rest = 60  # Default fallback value
        
        return hr_rest
    
    def get_max_heart_rate(self):
        """Get the athlete's max heart rate from cached zones estimated as Z4_max."""
        zones = self.strava_user_cache.get_athlete_zones()
        hr_max = zones['heart_rate']['zones'][3]['max']
        return hr_max

    def get_current_vo2_max(self):
        """
        Calculate VO2 Max based on Uth-Sørensen-Overgaard-Pedersen estimation:
            VO2 Max = 15.3 x (HR_max / HR_rest)

            It is static as Strava does not provide the historical heart rate data via API.
        """
        hr_max = self.get_max_heart_rate()
        hr_rest = self.get_rest_heart_rate()

        vo2_max_value = vo2_max(hr_max, hr_rest)
        return round(vo2_max_value, 2)
    

    """
    ==================
    ACTIVITY ANALYTICS
    ==================
    """