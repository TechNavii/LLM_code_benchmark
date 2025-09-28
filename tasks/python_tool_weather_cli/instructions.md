# Task: Integrate weather tool (Python)

Use the provided CLI tool `tools/weather_tool.py` to fetch weather data for a city. Implement `weather_service.get_weather` so that it:

- Validates the city argument (non-empty after trimming) and raises `RuntimeError` otherwise.
- Executes the weather tool via subprocess, passing the city name.
- Parses the JSON payload printed by the tool and returns it as a dictionary.
- Raises `RuntimeError` with helpful context if the tool exits non-zero or if the output is invalid JSON.

The tool writes a random token to `.last_call`; tests rely on this side effect to confirm the tool was invoked.

## Testing
```
pytest -q
```
