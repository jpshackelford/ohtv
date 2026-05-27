# Customizing Prompts: `ohtv prompts`

All LLM analyses are driven by editable Markdown prompts shipped with the package. You can copy them to `~/.ohtv/prompts/` and edit them to suit your workflow.

## `ohtv prompts` - Manage Analysis Prompts

View and customize the LLM prompts used for analysis. Prompts are organized into families (e.g., `objs`) with variants (e.g., `brief`, `detailed_assess`).

```bash
# List all prompts and their status
ohtv prompts
ohtv prompts list

# Show a specific prompt's content
ohtv prompts show brief
ohtv prompts show objs/detailed_assess

# Copy prompts to ~/.ohtv/prompts/ for customization
ohtv prompts init

# Reset a customized prompt to default
ohtv prompts reset brief
ohtv prompts reset objs/brief

# Reset all prompts to defaults
ohtv prompts reset --all
```

**Example Output (list):**
```
Prompt Families:

  code_review/
    default               (default) Analyze code changes made during the conversation

  objs/
    brief                 (default) Extract user goal in 1-2 sentences
    brief_assess                    Extract user goal and assess completion status
    detailed                        Extract hierarchical objectives with subordinate goals
    detailed_assess                 Extract hierarchical objectives and assess completion status
    standard                        Extract primary and secondary outcomes
    standard_assess                 Extract primary and secondary outcomes and assess completion

User prompts directory: ~/.ohtv/prompts
Run 'ohtv prompts init' to copy prompts for customization.
```

**Customizing Prompts:**

1. Run `ohtv prompts init` to copy default prompts to `~/.ohtv/prompts/`
2. Edit the prompt files (they use YAML frontmatter + Markdown body)
3. Your changes take effect immediately (cache is invalidated automatically)
4. Use `ohtv prompts reset <name>` to restore a prompt to default

**Prompt File Structure:**
```yaml
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
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent

output:
  schema:
    goal: string
---
Your prompt instructions here...

Respond with JSON:
{"goal": "1-2 sentence description"}
```

**Options:**
| Flag | Description |
|------|-------------|
| `--all` | Reset all prompts (with `reset` action) |

---

