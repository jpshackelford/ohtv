#!/usr/bin/env python3
"""Experimental script to analyze interaction patterns in trajectories.

This script validates the heuristics proposed in SPEC_REFS_INTERACTION_TYPES.md
by scanning actual trajectory data and looking for:
1. Commands that indicate interactions (gh pr, gh issue, git push)
2. Successful outputs that confirm the interaction happened
3. Correlation between detected commands and refs URLs
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class InteractionPattern:
    """A detected interaction pattern."""
    conv_id: str
    event_id: str
    command: str
    pattern_type: str  # push, pr_create, pr_comment, pr_merge, issue_create, issue_comment
    success: bool
    output_snippet: str
    extracted_ref: str | None = None


@dataclass 
class ConversationAnalysis:
    """Analysis results for a conversation."""
    conv_id: str
    refs_found: dict[str, set[str]] = field(default_factory=lambda: {"repos": set(), "prs": set(), "issues": set()})
    interactions: list[InteractionPattern] = field(default_factory=list)


# Patterns to detect in commands
COMMAND_PATTERNS = {
    "git_push": re.compile(r"git\s+push(?:\s+--[a-z-]+)*\s+(\S+)(?:\s+(\S+))?"),
    "gh_pr_create": re.compile(r"gh\s+pr\s+create"),
    "gh_pr_comment": re.compile(r"gh\s+pr\s+comment\s+(\d+)"),
    "gh_pr_review": re.compile(r"gh\s+pr\s+review\s+(\d+)"),  # gh pr review 28 --comment
    "gh_pr_merge": re.compile(r"gh\s+pr\s+merge\s+(\d+)"),
    "gh_pr_close": re.compile(r"gh\s+pr\s+close\s+(\d+)"),
    "gh_issue_create": re.compile(r"gh\s+issue\s+create"),
    "gh_issue_comment": re.compile(r"gh\s+issue\s+comment\s+(\d+)"),
    "gh_issue_close": re.compile(r"gh\s+issue\s+close\s+(\d+)"),
    # GraphQL API patterns
    "gh_api_comment": re.compile(r"gh\s+api\s+graphql.*addPullRequestReview", re.DOTALL),
    "gh_api_resolve": re.compile(r"gh\s+api\s+graphql.*resolveReviewThread", re.DOTALL),
}

# Success indicators in outputs
SUCCESS_PATTERNS = {
    "git_push": [
        re.compile(r"To\s+(https://github\.com/[^\s]+\.git)"),
        re.compile(r"Branch '([^']+)' set up to track"),
        re.compile(r"(\S+)\s*->\s*(\S+)"),  # branch -> branch
    ],
    "gh_pr_create": [
        re.compile(r"https://github\.com/[^/]+/[^/]+/pull/(\d+)"),
        re.compile(r"Creating pull request"),
    ],
    "gh_pr_merge": [
        re.compile(r"✓ (Squashed and merged|Merged|Rebased and merged) pull request"),
    ],
    "gh_pr_review": [
        # gh pr review often has no explicit success output, check exit code
    ],
    "gh_pr_comment": [
        re.compile(r"https://github\.com/[^/]+/[^/]+/pull/\d+#"),
    ],
    "gh_issue_create": [
        re.compile(r"https://github\.com/[^/]+/[^/]+/issues/(\d+)"),
    ],
}


def analyze_conversation(conv_dir: Path) -> ConversationAnalysis:
    """Analyze a conversation for interaction patterns."""
    analysis = ConversationAnalysis(conv_id=conv_dir.name)
    events_dir = conv_dir / "events"
    
    if not events_dir.exists():
        return analysis
    
    # Load all events
    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            event = json.loads(event_file.read_text())
            event["_file"] = event_file.name
            events.append(event)
        except (json.JSONDecodeError, OSError):
            continue
    
    # Scan for command patterns and their observations
    for i, event in enumerate(events):
        if event.get("kind") != "ActionEvent":
            continue
        
        action = event.get("action")
        if not action or action.get("kind") != "TerminalAction":
            continue
        
        command = action.get("command", "")
        if not command:
            continue
        
        # Check each pattern
        for pattern_name, pattern in COMMAND_PATTERNS.items():
            match = pattern.search(command)
            if match:
                # Look for the observation in the next event
                observation = None
                exit_code = None
                output = ""
                
                if i + 1 < len(events):
                    next_event = events[i + 1]
                    if next_event.get("kind") == "ObservationEvent":
                        obs = next_event.get("observation", {})
                        exit_code = obs.get("exit_code")
                        content = obs.get("content", [])
                        if content and isinstance(content, list):
                            output = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
                
                # Determine success
                success = exit_code == 0
                
                # Check for success patterns in output
                if pattern_name in SUCCESS_PATTERNS:
                    for success_pattern in SUCCESS_PATTERNS[pattern_name]:
                        if success_pattern.search(output):
                            success = True
                            break
                
                interaction = InteractionPattern(
                    conv_id=conv_dir.name,
                    event_id=event.get("id", ""),
                    command=command[:200],
                    pattern_type=pattern_name,
                    success=success,
                    output_snippet=output[:300] if output else "",
                )
                analysis.interactions.append(interaction)
    
    return analysis


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Analyze interaction patterns in trajectories")
    parser.add_argument("--cloud-dir", type=Path, default=Path.home() / ".openhands" / "cloud" / "conversations")
    parser.add_argument("--local-dir", type=Path, default=Path.home() / ".openhands" / "conversations")
    parser.add_argument("--limit", type=int, default=50, help="Max conversations to analyze")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    
    # Collect conversations
    conv_dirs = []
    for base_dir in [args.cloud_dir, args.local_dir]:
        if base_dir.exists():
            conv_dirs.extend(sorted(base_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:args.limit])
    
    print(f"Analyzing {len(conv_dirs)} conversations...")
    
    # Analyze
    results = defaultdict(list)
    total_interactions = 0
    successful_interactions = 0
    
    for conv_dir in conv_dirs[:args.limit]:
        if not conv_dir.is_dir():
            continue
        
        analysis = analyze_conversation(conv_dir)
        
        for interaction in analysis.interactions:
            results[interaction.pattern_type].append(interaction)
            total_interactions += 1
            if interaction.success:
                successful_interactions += 1
            
            if args.verbose:
                status = "✓" if interaction.success else "✗"
                print(f"\n{status} [{interaction.pattern_type}] {interaction.conv_id[:7]}")
                print(f"  Command: {interaction.command[:80]}...")
                if not interaction.success:
                    print(f"  Output: {interaction.output_snippet[:200]}...")
    
    # Summary
    print("\n" + "="*60)
    print("INTERACTION PATTERN ANALYSIS SUMMARY")
    print("="*60)
    
    for pattern_type, interactions in sorted(results.items()):
        successful = sum(1 for i in interactions if i.success)
        print(f"\n{pattern_type}:")
        print(f"  Total detected: {len(interactions)}")
        print(f"  Successful: {successful}")
        print(f"  Success rate: {successful/len(interactions)*100:.1f}%" if interactions else "  Success rate: N/A")
    
    print(f"\n{'='*60}")
    print(f"TOTAL: {total_interactions} interactions, {successful_interactions} successful")
    print(f"Overall success detection rate: {successful_interactions/total_interactions*100:.1f}%" if total_interactions else "N/A")


if __name__ == "__main__":
    main()
