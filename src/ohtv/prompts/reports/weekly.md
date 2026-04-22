---
id: reports.weekly
description: Generate a weekly summary of work accomplished

input:
  mode: aggregate
  source: objs.brief
  period: week
  min_items: 1

output:
  schema:
    type: object
    required: [summary, themes, stats]
    properties:
      summary:
        type: string
        description: 2-3 sentence overview of the week's work
      themes:
        type: array
        items:
          type: string
        description: Major themes or focus areas identified
      highlights:
        type: array
        items:
          type: string
        description: Key accomplishments or notable work items
      stats:
        type: object
        properties:
          conversation_count:
            type: integer
          estimated_hours:
            type: number

display:
  table:
    columns:
      - name: Period
        field: period.label
        width: 20
      - name: Items
        field: items_count
        width: 8
      - name: Summary
        field: summary
      - name: Themes
        field: themes
        format: list
---
{% if items %}
Analyze the following {{ items | length }} conversations from {{ period.label }}:

{% for item in items %}
## [{{ item.conversation_id[:8] }}] {{ item.created_at[:10] if item.created_at else 'Unknown date' }}
Goal: {{ item.result.goal if item.result.goal else 'Unknown' }}
{% endfor %}

Generate a weekly summary with:
1. A 2-3 sentence **summary** of what was accomplished this week
2. **themes** - list of 2-5 major focus areas or recurring topics
3. **highlights** - list of 3-5 key accomplishments or notable items
4. **stats** with:
   - conversation_count: the number of conversations ({{ items | length }})
   - estimated_hours: rough estimate of hours spent based on conversation complexity

Respond with JSON matching the output schema.
{% else %}
No conversations found for {{ period.label }}.

Generate an empty weekly report with:
- summary: "No work sessions recorded for this period."
- themes: []
- highlights: []
- stats: { conversation_count: 0, estimated_hours: 0 }

Respond with JSON.
{% endif %}
