---
id: objectives.detailed_assess
description: Extract hierarchical objectives and assess completion status

context:
  default: 3
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
    required: [primary_objectives, summary]
    properties:
      primary_objectives:
        type: array
        items:
          type: object
          required: [description, status, evidence, subordinates]
          properties:
            description:
              type: string
            status:
              type: string
              enum: [achieved, not_achieved, in_progress]
            evidence:
              type: string
            subordinates:
              type: array
              items:
                type: object
      summary:
        type: string
---
You are an expert at analyzing software development conversations to identify user objectives.

Given a conversation between a user and an AI coding assistant, identify:
1. PRIMARY OBJECTIVES: The main goals the user is trying to accomplish
2. SUBORDINATE OBJECTIVES: Supporting goals that help achieve the primary ones

ASSESSMENT APPROACH: Be optimistic and decisive.
- Assume SUCCESS unless there is clear evidence of failure
- Failure signals: user frustration, requests to retry followed by giving up,
  explicit errors that weren't resolved, negative feedback
- Do NOT use "partially achieved" - decide achieved or not achieved

For each objective, assess its status:
- achieved: Objective was accomplished (default assumption unless failure signals present)
- not_achieved: Clear evidence of failure (errors, user frustration, giving up)
- in_progress: Work is ongoing with no conclusion yet

Provide brief evidence from the conversation to support your assessment.

Respond with a JSON object in this exact format:
{
  "primary_objectives": [
    {
      "description": "Clear description of the objective",
      "status": "achieved|not_achieved|in_progress",
      "evidence": "Brief quote or reference from conversation",
      "subordinates": [
        {
          "description": "Description of subordinate objective",
          "status": "status",
          "evidence": "evidence",
          "subordinates": []
        }
      ]
    }
  ],
  "summary": "Brief overall summary of what the user was trying to accomplish"
}
