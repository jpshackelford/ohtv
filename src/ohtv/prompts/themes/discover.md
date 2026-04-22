---
id: themes.discover
description: Find common themes across all selected conversations

input:
  mode: aggregate
  source: objs.brief
  # No period - aggregates entire selection into one output
  min_items: 2

output:
  schema:
    type: object
    required: [themes]
    properties:
      themes:
        type: array
        items:
          type: object
          properties:
            name:
              type: string
              description: Theme name (2-4 words)
            description:
              type: string
              description: Brief description of the theme
            frequency:
              type: integer
              description: Number of conversations touching this theme
            example_goals:
              type: array
              items:
                type: string
              description: 1-3 example goals from conversations
      patterns:
        type: object
        properties:
          most_common_type:
            type: string
            description: Most common type of work (e.g., bugfix, feature, refactor)
          tech_stack:
            type: array
            items:
              type: string
            description: Technologies/frameworks frequently mentioned
---
Analyze the following {{ items | length }} conversations to identify common themes and patterns:

{% for item in items %}
- [{{ item.conversation_id[:8] }}] {{ item.result.goal if item.result.goal else 'Unknown goal' }}
{% endfor %}

Identify:
1. **themes** - recurring topics or focus areas that appear across multiple conversations
   - For each theme, provide:
     - name: 2-4 word theme name
     - description: what this theme encompasses
     - frequency: how many conversations touch this theme
     - example_goals: 1-3 example goals that relate to this theme

2. **patterns** - meta-analysis of work patterns:
   - most_common_type: the dominant type of work (bugfix, feature, refactor, documentation, etc.)
   - tech_stack: technologies or frameworks that appear frequently

Focus on substantive themes, not superficial groupings. A theme should represent a meaningful category of work or focus area.

Respond with JSON matching the output schema.
