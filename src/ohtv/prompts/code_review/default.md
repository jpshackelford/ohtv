---
id: code_review.default
description: Analyze code changes made during the conversation
default: true

context:
  default: 1
  levels:
    1:
      name: edits_only
      include:
        - source: agent
          kind: ActionEvent
          tool: file_editor
    2:
      name: with_commands
      include:
        - source: agent
          kind: ActionEvent
          tool: file_editor
        - source: agent
          kind: ActionEvent
          tool: terminal
      truncate: 500
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      truncate: 300

output:
  schema:
    type: object
    required: [changes]
    properties:
      changes:
        type: array
        items:
          type: object
          properties:
            file:
              type: string
            action:
              type: string
            summary:
              type: string
---
Analyze the code changes made in this conversation.

For each file modified, identify:
- The file path
- Whether it was created, edited, or deleted
- A brief summary of the change

Respond with JSON:
{
  "changes": [
    {"file": "path/to/file.py", "action": "edit", "summary": "Added error handling"}
  ]
}
