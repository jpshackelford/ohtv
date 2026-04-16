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
