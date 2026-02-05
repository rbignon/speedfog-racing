# Integration Testing Design - Step 11

## Objective

End-to-end server-side tests that validate the complete race flow with multiple players.

## Approach

- Synchronous tests using Starlette's `TestClient`
- Simulate multiple mod clients connecting via WebSocket
- Validate leaderboard updates, state transitions, and error handling

## Test Scenarios

### Scenario 1: Complete Race Flow (3 Players)

```
1. Setup: organizer creates race, adds 3 participants, generates zips
2. 3 mods connect and authenticate → receive auth_ok
3. All send ready
4. Organizer starts race → all receive race_start
5. Player A: status_update + zone_entered (layer 1)
6. Player B: zone_entered (layer 2) → B ahead of A in leaderboard
7. Player C: zone_entered (layer 2, better IGT) → C ahead of B
8. Player C: finished → C leads (finished status)
9. Player A: finished (longer IGT) → A second
10. Verify final states in DB
```

### Scenario 2: Error Handling

- Invalid auth token → auth_error, connection closed
- Malformed JSON message → ignored, connection maintained
- Duplicate connection same participant → first connection closed

## Technical Implementation

### ModTestClient Helper

```python
class ModTestClient:
    """Simulates a mod connecting to the race WebSocket."""

    def __init__(self, test_client, race_id: str, mod_token: str):
        self.race_id = race_id
        self.mod_token = mod_token
        self.ws = None

    def connect(self):
        """Connect to WebSocket."""
        self.ws = test_client.websocket_connect(f"/ws/mod/{self.race_id}")
        return self

    def auth(self) -> dict:
        """Send auth and return response."""
        self.ws.send_json({"type": "auth", "mod_token": self.mod_token})
        return self.ws.receive_json()

    def send_ready(self): ...
    def send_status_update(self, igt_ms, zone, deaths): ...
    def send_zone_entered(self, from_zone, to_zone, igt_ms): ...
    def send_finished(self, igt_ms): ...
    def receive(self) -> dict: ...
    def close(self): ...
```

### File Structure

```
tests/
├── conftest.py           # Existing + new fixtures
└── test_integration.py   # New - E2E tests
```

## Implementation Steps

1. Create `ModTestClient` helper class
2. Add fixtures for race with multiple participants
3. Implement Scenario 1 (complete race flow)
4. Implement Scenario 2 (error handling)
5. Verify all tests pass
