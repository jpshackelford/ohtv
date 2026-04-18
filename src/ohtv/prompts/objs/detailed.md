---
id: objs.detailed
description: Extract hierarchical objectives with subordinate goals

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
          required: [description, subordinates]
          properties:
            description:
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

Do not assess whether objectives were achieved. Just identify what the user wants to accomplish
and structure them hierarchically.

Respond with a JSON object in this exact format:
{
  "primary_objectives": [
    {
      "description": "Clear description of the objective",
      "subordinates": [
        {
          "description": "Description of subordinate objective",
          "subordinates": []
        }
      ]
    }
  ],
  "summary": "Brief overall summary of what the user was trying to accomplish"
}
