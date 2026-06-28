"""Instant-lane health tools -- thin wrappers over HealthAgent methods."""


def log_meal(description: str) -> str:
    """Log a meal from a text description like '200g chicken breast and 150g rice'."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "Set up your health profile first -- tell me your age, weight, height, and goal."
    return agent._log_meal(description, profile)


def log_workout(description: str) -> str:
    """Log a workout session like 'chest day: bench press 4x8 at 80kg'."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "Set up your health profile first."
    return agent._log_workout(description, profile)


def nutrition_summary() -> str:
    """Return today's calorie and macro progress vs targets."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "No health profile set up yet."
    return agent._nutrition_summary(profile)


def todays_workout() -> str:
    """Return today's scheduled training session based on Mo's program."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "No health profile set up yet."
    return agent._todays_workout(profile)
