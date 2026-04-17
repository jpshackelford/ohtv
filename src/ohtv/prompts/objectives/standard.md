---
id: objectives.standard
description: Extract primary and secondary outcomes

context:
  default: 2
  levels:
    1:
      name: minimal
      include:
        - source: user
          kind: MessageEvent
    2:
      name: default
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      truncate: 1000

output:
  schema:
    type: object
    required: [goal, primary_outcomes, secondary_outcomes]
    properties:
      goal:
        type: string
      primary_outcomes:
        type: array
        items:
          type: string
      secondary_outcomes:
        type: array
        items:
          type: string
---
Analyze this conversation between a user and an AI coding assistant.

Identify:
1. The user's primary goal (1-2 sentences)
2. Primary outcomes or success criteria (3-6 bullets max)
3. Secondary outcomes if any (3-6 bullets max)

Do not assess whether goals were achieved. Just identify what the user wants.

Respond with JSON:
{
  "goal": "1-2 sentence description of the primary goal",
  "primary_outcomes": ["outcome 1", "outcome 2"],
  "secondary_outcomes": ["outcome 1", "outcome 2"]
}
