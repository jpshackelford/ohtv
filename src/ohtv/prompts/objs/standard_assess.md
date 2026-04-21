---
id: objs.standard_assess
description: Extract primary and secondary outcomes and assess completion

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
    required: [goal, status, primary_outcomes, secondary_outcomes]
    properties:
      goal:
        type: string
      status:
        type: string
        enum: [achieved, not_achieved, in_progress]
      primary_outcomes:
        type: array
        items:
          type: string
      secondary_outcomes:
        type: array
        items:
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
      - name: Status
        field: status
        format: status_badge
        width: 6
      - name: Summary
        fields:
          - goal
          - field: primary_outcomes
            format: bullet_list
            prefix: "Primary:"
          - field: secondary_outcomes
            format: bullet_list
            prefix: "Secondary:"
          - refs_display
        combine: newline
---
Analyze this conversation between a user and an AI coding assistant.

Identify:
1. The user's primary goal (1-2 sentences)
2. Primary outcomes or success criteria (3-6 bullets max)
3. Secondary outcomes if any (3-6 bullets max)
4. Overall status of goal achievement

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
  "goal": "1-2 sentence description of the primary goal",
  "status": "achieved|not_achieved|in_progress",
  "primary_outcomes": ["outcome 1", "outcome 2"],
  "secondary_outcomes": ["outcome 1", "outcome 2"]
}
