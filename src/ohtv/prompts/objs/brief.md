---
id: objs.brief
description: Extract user goal in 1-2 sentences
default: true

context:
  default: 1
  levels:
    1:
      name: minimal
      include:
        - source: user
          kind: MessageEvent
      truncate: 500
    2:
      name: outcome
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish
      truncate: 1000
    3:
      name: dialogue
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish
      truncate: 1000
    4:
      name: actions
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      truncate: 2000
    5:
      name: observations
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
        - kind: ObservationEvent
      truncate: 800

output:
  schema:
    type: object
    required: [goal]
    properties:
      goal:
        type: string

display:
  table:
    columns:
      - name: ID
        fields:
          - short_id
          - source
        combine: newline
        width: 9
      - name: Date
        fields:
          - field: created_at
            format: date
          - field: created_at
            format: time
        combine: newline
        width: 12
      - name: Duration
        fields:
          - field: duration
            format: duration_minutes
          - field: event_count
            format: step_count
        combine: newline
        width: 10
      - name: Summary
        fields:
          - goal
          - refs_display
        combine: newline
---
Analyze this conversation between a user and an AI coding assistant.

In 1-2 sentences, describe the user's goal using imperative mood (e.g., "Add pagination to search results" not "The user wants to add pagination").

Do not assess whether the goal was achieved. Just identify what they want.

Respond with JSON:
{"goal": "1-2 sentence description in imperative mood"}
