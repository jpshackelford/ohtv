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
      name: default
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish
      truncate: 1000
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      truncate: 2000

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
        field: short_id
        width: 7
      - name: Date
        field: created_at
        format: date
        width: 10
      - name: Summary
        field: goal
---
Analyze this conversation between a user and an AI coding assistant.

In 1-2 sentences, describe the user's goal using imperative mood (e.g., "Add pagination to search results" not "The user wants to add pagination").

Do not assess whether the goal was achieved. Just identify what they want.

Respond with JSON:
{"goal": "1-2 sentence description in imperative mood"}
