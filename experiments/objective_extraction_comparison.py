#!/usr/bin/env python3
"""Compare different approaches to objective extraction.

This experiment tests multiple strategies for extracting user objectives
from conversations, comparing token usage vs. quality of results.

Approaches tested:
1. user_only: Just user messages (minimal tokens)
2. user_plus_finish: User messages + finish action (shows outcome)
3. user_plus_summaries: User messages + action summaries (shows what was tried)
4. user_agent: User + agent messages (no tool details)
5. full: Everything including tool outputs (maximum context)
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ohtv.config import Config


@dataclass
class ExtractionApproach:
    """Configuration for an extraction approach."""
    name: str
    description: str
    include_user: bool = True
    include_agent_messages: bool = False
    include_action_summaries: bool = False
    include_finish: bool = False
    include_outputs: bool = False


APPROACHES = [
    ExtractionApproach(
        name="user_only",
        description="User messages only (minimal tokens)",
        include_user=True,
    ),
    ExtractionApproach(
        name="user_plus_finish",
        description="User messages + finish action",
        include_user=True,
        include_finish=True,
    ),
    ExtractionApproach(
        name="user_plus_summaries",
        description="User messages + action summaries",
        include_user=True,
        include_action_summaries=True,
    ),
    ExtractionApproach(
        name="user_agent",
        description="User + agent messages (current approach)",
        include_user=True,
        include_agent_messages=True,
    ),
    ExtractionApproach(
        name="full",
        description="Full context including outputs",
        include_user=True,
        include_agent_messages=True,
        include_action_summaries=True,
        include_finish=True,
        include_outputs=True,
    ),
]


def load_events(conv_dir: Path) -> list[dict]:
    """Load all events from a conversation directory."""
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return []

    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(event_file.read_text())
            events.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return events


def extract_message_content(event: dict) -> str:
    """Extract text content from a message event."""
    llm_msg = event.get("llm_message", {})
    content = llm_msg.get("content", [])

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

    if isinstance(content, str):
        return content

    return event.get("content", "") or event.get("message", "")


def extract_action_summary(event: dict) -> str:
    """Extract a brief summary of an action."""
    tool_name = event.get("tool_name", "unknown")
    action = event.get("action", {})
    
    # Get key details based on tool type
    if tool_name == "terminal":
        cmd = action.get("command", "")[:100]
        return f"[Terminal] {cmd}"
    elif tool_name == "file_editor":
        path = action.get("path", "")
        cmd = action.get("command", "")
        return f"[Edit] {cmd} {path}"
    elif tool_name == "finish":
        msg = action.get("message", "")[:200]
        return f"[Finish] {msg}"
    else:
        return f"[{tool_name}]"


def extract_observation_content(event: dict) -> str:
    """Extract content from an observation event."""
    obs = event.get("observation", {})
    content = obs.get("content", [])

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        text = "\n".join(texts)
    elif isinstance(content, str):
        text = content
    else:
        text = ""
    
    # Truncate long outputs
    if len(text) > 500:
        text = text[:500] + "... [truncated]"
    return text


def build_transcript(events: list[dict], approach: ExtractionApproach) -> str:
    """Build a transcript based on the approach configuration."""
    lines = []
    
    for i, event in enumerate(events):
        source = event.get("source", "")
        kind = event.get("kind", "")
        
        # User messages
        if source == "user" and kind == "MessageEvent" and approach.include_user:
            content = extract_message_content(event)
            if content:
                lines.append(f"[USER]: {content}")
        
        # Agent messages
        elif source == "agent" and kind == "MessageEvent" and approach.include_agent_messages:
            content = extract_message_content(event)
            if content:
                # Truncate long agent messages
                if len(content) > 1000:
                    content = content[:1000] + "... [truncated]"
                lines.append(f"[ASSISTANT]: {content}")
        
        # Action events
        elif source == "agent" and kind == "ActionEvent":
            tool_name = event.get("tool_name", "")
            
            # Finish action
            if tool_name == "finish" and approach.include_finish:
                summary = extract_action_summary(event)
                lines.append(f"[ACTION]: {summary}")
            
            # Other actions (summaries only)
            elif approach.include_action_summaries and tool_name != "finish":
                summary = extract_action_summary(event)
                lines.append(f"[ACTION]: {summary}")
        
        # Observations (tool outputs)
        elif source == "environment" and kind == "ObservationEvent" and approach.include_outputs:
            content = extract_observation_content(event)
            if content:
                lines.append(f"[OUTPUT]: {content}")
    
    return "\n\n".join(lines)


def count_tokens_approximate(text: str) -> int:
    """Rough token count (words * 1.3 as approximation)."""
    words = len(text.split())
    return int(words * 1.3)


def run_comparison(conv_dir: Path) -> dict:
    """Run all approaches on a conversation and compare results."""
    events = load_events(conv_dir)
    if not events:
        return {"error": "No events found"}
    
    results = {}
    for approach in APPROACHES:
        transcript = build_transcript(events, approach)
        token_count = count_tokens_approximate(transcript)
        
        results[approach.name] = {
            "description": approach.description,
            "transcript_chars": len(transcript),
            "approx_tokens": token_count,
            "transcript_preview": transcript[:500] + "..." if len(transcript) > 500 else transcript,
        }
    
    return results


def run_llm_comparison(conv_dir: Path, model: str | None = None) -> dict:
    """Run LLM analysis with each approach and compare outputs."""
    # Suppress SDK banner
    os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
    
    from openhands.sdk import LLM, Message, TextContent
    
    events = load_events(conv_dir)
    if not events:
        return {"error": "No events found"}
    
    # Load LLM
    llm = LLM.load_from_env()
    if model:
        llm = LLM(model=model, api_key=llm.api_key, base_url=llm.base_url)
    
    system_prompt = """Analyze this conversation and identify user objectives.

For each objective, assess its status:
- achieved: Fully accomplished
- partially_achieved: Some progress made
- not_achieved: Not accomplished
- in_progress: Work ongoing
- unclear: Cannot determine

Respond with JSON:
{
  "primary_objectives": [
    {
      "description": "Objective description",
      "status": "status",
      "evidence": "Brief evidence",
      "subordinates": []
    }
  ],
  "summary": "Brief summary"
}"""
    
    results = {}
    
    for approach in APPROACHES:
        print(f"\n{'='*60}")
        print(f"Testing: {approach.name} - {approach.description}")
        print(f"{'='*60}")
        
        transcript = build_transcript(events, approach)
        approx_tokens = count_tokens_approximate(transcript)
        
        print(f"Approximate input tokens: {approx_tokens}")
        print(f"Transcript preview:\n{transcript[:300]}...")
        
        # Call LLM
        messages = [
            Message(role="system", content=[TextContent(type="text", text=system_prompt)]),
            Message(role="user", content=[TextContent(type="text", text=f"Analyze:\n\n{transcript}")]),
        ]
        
        try:
            response = llm.completion(messages)
            response_text = ""
            for item in response.message.content:
                if hasattr(item, "text"):
                    response_text += item.text
            
            # Parse JSON
            text = response_text.strip()
            if text.startswith("```"):
                lines = text.split("\n")[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            
            analysis = json.loads(text)
            
            results[approach.name] = {
                "description": approach.description,
                "approx_input_tokens": approx_tokens,
                "analysis": analysis,
                "success": True,
            }
            
            # Print summary
            print(f"\nObjectives found: {len(analysis.get('primary_objectives', []))}")
            print(f"Summary: {analysis.get('summary', 'N/A')[:100]}...")
            
        except Exception as e:
            results[approach.name] = {
                "description": approach.description,
                "approx_input_tokens": approx_tokens,
                "error": str(e),
                "success": False,
            }
            print(f"Error: {e}")
    
    return results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Compare objective extraction approaches")
    parser.add_argument("conversation_id", help="Conversation ID or prefix")
    parser.add_argument("--llm", action="store_true", help="Run LLM comparison (costs tokens)")
    parser.add_argument("--model", help="LLM model to use")
    parser.add_argument("--output", "-o", help="Output file for results JSON")
    
    args = parser.parse_args()
    
    # Find conversation
    config = Config.from_env()
    conv_dir = None
    
    for base_dir in [config.local_conversations_dir, config.cloud_conversations_dir]:
        if not base_dir.exists():
            continue
        exact = base_dir / args.conversation_id
        if exact.exists():
            conv_dir = exact
            break
        matches = [d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith(args.conversation_id)]
        if len(matches) == 1:
            conv_dir = matches[0]
            break
    
    if not conv_dir:
        print(f"Error: Conversation '{args.conversation_id}' not found")
        sys.exit(1)
    
    print(f"Analyzing conversation: {conv_dir.name}")
    
    if args.llm:
        results = run_llm_comparison(conv_dir, args.model)
    else:
        results = run_comparison(conv_dir)
        
        # Print comparison
        print("\n" + "="*70)
        print("APPROACH COMPARISON")
        print("="*70)
        print(f"{'Approach':<25} {'Tokens':>10} {'Chars':>10}")
        print("-"*70)
        for name, data in results.items():
            print(f"{name:<25} {data['approx_tokens']:>10} {data['transcript_chars']:>10}")
    
    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    main()
