# Weather API Specification

## Base URL
`https://api.weather.example.com/v1`

## Endpoints

### GET /current?city={city}
Returns current weather for a city.

Response:
```json
{"city": "Beijing", "temp_c": 22.5, "humidity": 65, "condition": "Sunny"}
```

### GET /forecast?city={city}&days={days}
Returns forecast for N days.

Response:
```json
{"city": "Beijing", "days": 3, "forecast": [
  {"date": "2024-03-16", "high": 25, "low": 12, "condition": "Sunny"},
  {"date": "2024-03-17", "high": 20, "low": 10, "condition": "Cloudy"}
]}
```

### POST /alert
Subscribe to weather alerts.

Request body:
```json
{"city": "Beijing", "threshold_temp_c": 35, "callback_url": "https://example.com/hook"}
```

Response:
```json
{"alert_id": "a123", "status": "active"}
```

## Authentication
All requests require header: `X-API-Key: <key>`

## Error Codes
- 400: Bad request
- 401: Invalid API key
- 404: City not found
- 429: Rate limited
