# TODO API Specification

## Overview
A simple REST API for managing TODO items with SQLite storage.

## Data Model

### Todo Item
| Field       | Type    | Required | Description                    |
|-------------|---------|----------|--------------------------------|
| id          | integer | auto     | Auto-increment primary key     |
| title       | string  | yes      | Todo title (1-200 chars)       |
| description | string  | no       | Optional description           |
| completed   | boolean | no       | Default: false                 |
| priority    | string  | no       | "low", "medium", "high". Default: "medium" |
| created_at  | string  | auto     | ISO 8601 timestamp             |

## Endpoints

### GET /todos
List all todos. Supports query parameter `?completed=true|false` for filtering.
- Response: `200` with JSON array of todo objects

### GET /todos/<id>
Get a single todo by ID.
- Response: `200` with todo object, or `404` if not found

### POST /todos
Create a new todo.
- Request body: `{"title": "...", "description": "...", "priority": "..."}`
- `title` is required, others optional
- Response: `201` with created todo object
- Error: `400` if title is missing or empty

### PUT /todos/<id>
Update an existing todo.
- Request body: any subset of `{title, description, completed, priority}`
- Response: `200` with updated todo object
- Error: `404` if not found

### DELETE /todos/<id>
Delete a todo.
- Response: `200` with `{"message": "deleted"}`
- Error: `404` if not found

## Error Format
```json
{"error": "description of the error"}
```

## Database
- Use SQLite with file `todos.db`
- Create table automatically on startup
