---
id: objs.brief_assess
description: Extract user goal and assess completion status

context:
  default: 2
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
    required: [goal, status]
    properties:
      goal:
        type: string
      status:
        type: string
        enum: [achieved, not_achieved, in_progress]
---
Analyze this conversation between a user and an AI coding assistant.

1. In 1-2 sentences, describe: What outcome does the user hope to achieve?
2. Assess whether the goal was achieved.

ASSESSMENT APPROACH: Be optimistic and decisive.
- Assume SUCCESS unless there is clear evidence of failure
- Failure signals: user frustration, requests to retry followed by giving up,
  explicit errors that weren't resolved, negative feedback
- Do NOT use "partially achieved" - decide achieved or not achieved

Status values:
- achieved: Goal was accomplished (default assumption unless failure signals present)
- not_achieved: Clear evidence of failure (errors, user frustration, giving up)
- in_progress: Conversation ended mid-work with no conclusion

Respond with JSON:
{
  "goal": "1-2 sentence description of what the user wants to accomplish",
  "status": "achieved|not_achieved|in_progress"
}
