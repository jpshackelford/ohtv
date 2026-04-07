#!/usr/bin/env python3
"""Analyze correlation between detected interactions and refs URLs.

This script extends analyze_interactions.py to answer:
1. Can we extract a specific repo/PR/issue from each command?
2. Does that extracted ref match one of the refs found in the conversation?
3. What's the correlation accuracy?
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ExtractedRef:
    """A reference extracted from a command."""
    ref_type: str  # "repo", "pr", "issue"
    owner: str | None
    repo: str | None
    number: int | None  # PR or issue number
    url: str | None  # Constructed URL if possible
    source: str  # "command" or "output"
    raw_match: str  # The raw text that was matched


@dataclass
class InteractionWithRef:
    """An interaction with its extracted reference."""
    conv_id: str
    event_id: str
    command: str
    pattern_type: str
    success: bool
    extracted_ref: ExtractedRef | None
    output_snippet: str
    matched_in_refs: bool = False  # Did we find this in the conversation's refs?


# Patterns to extract repo/PR/issue from commands
# gh pr comment 123 --repo owner/repo
REPO_FLAG_PATTERN = re.compile(r"--repo\s+([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)")

# gh pr view 123, gh issue comment 42, etc.
NUMBER_PATTERNS = {
    "pr": re.compile(r"gh\s+pr\s+(?:view|comment|review|merge|close|checks|diff)\s+(\d+)"),
    "issue": re.compile(r"gh\s+issue\s+(?:view|comment|close)\s+(\d+)"),
}

# git push origin branch-name -> need to find repo from git remote or working dir
GIT_PUSH_PATTERN = re.compile(r"git\s+push(?:\s+--[a-z-]+)*\s+(\S+)(?:\s+(\S+))?")

# Extract repo from output "To https://github.com/owner/repo.git"
OUTPUT_REPO_PATTERN = re.compile(r"To\s+https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)(?:\.git)?")

# Extract PR URL from output "https://github.com/owner/repo/pull/123"
OUTPUT_PR_PATTERN = re.compile(r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/pull/(\d+)")

# Extract issue URL from output
OUTPUT_ISSUE_PATTERN = re.compile(r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/issues/(\d+)")

# Merge success pattern with PR info
MERGE_SUCCESS_PATTERN = re.compile(r"✓\s+(?:Squashed and merged|Merged|Rebased and merged)\s+pull request\s+([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)#(\d+)")


def extract_ref_from_command(command: str, output: str, pattern_type: str) -> ExtractedRef | None:
    """Extract the target ref from a command and its output."""
    
    # First, try to get repo from --repo flag (most reliable)
    repo_match = REPO_FLAG_PATTERN.search(command)
    owner, repo = (repo_match.group(1), repo_match.group(2)) if repo_match else (None, None)
    
    # For PR commands, extract number
    if pattern_type in ("gh_pr_comment", "gh_pr_review", "gh_pr_merge", "gh_pr_close"):
        num_match = NUMBER_PATTERNS["pr"].search(command)
        if num_match:
            number = int(num_match.group(1))
            if owner and repo:
                return ExtractedRef(
                    ref_type="pr",
                    owner=owner,
                    repo=repo,
                    number=number,
                    url=f"https://github.com/{owner}/{repo}/pull/{number}",
                    source="command",
                    raw_match=f"{owner}/{repo}#{number}"
                )
            # Try to get repo from output
            pr_url_match = OUTPUT_PR_PATTERN.search(output)
            if pr_url_match:
                return ExtractedRef(
                    ref_type="pr",
                    owner=pr_url_match.group(1),
                    repo=pr_url_match.group(2),
                    number=int(pr_url_match.group(3)),
                    url=f"https://github.com/{pr_url_match.group(1)}/{pr_url_match.group(2)}/pull/{pr_url_match.group(3)}",
                    source="output",
                    raw_match=pr_url_match.group(0)
                )
            # Partial match - we have PR number but no repo
            return ExtractedRef(
                ref_type="pr",
                owner=None,
                repo=None,
                number=number,
                url=None,
                source="command",
                raw_match=f"PR #{number} (repo unknown)"
            )
    
    # For issue commands
    if pattern_type in ("gh_issue_comment", "gh_issue_close"):
        num_match = NUMBER_PATTERNS["issue"].search(command)
        if num_match:
            number = int(num_match.group(1))
            if owner and repo:
                return ExtractedRef(
                    ref_type="issue",
                    owner=owner,
                    repo=repo,
                    number=number,
                    url=f"https://github.com/{owner}/{repo}/issues/{number}",
                    source="command",
                    raw_match=f"{owner}/{repo}#{number}"
                )
            # Partial match
            return ExtractedRef(
                ref_type="issue",
                owner=None,
                repo=None,
                number=number,
                url=None,
                source="command",
                raw_match=f"Issue #{number} (repo unknown)"
            )
    
    # For gh pr create - look for created PR URL in output
    if pattern_type == "gh_pr_create":
        pr_url_match = OUTPUT_PR_PATTERN.search(output)
        if pr_url_match:
            return ExtractedRef(
                ref_type="pr",
                owner=pr_url_match.group(1),
                repo=pr_url_match.group(2),
                number=int(pr_url_match.group(3)),
                url=f"https://github.com/{pr_url_match.group(1)}/{pr_url_match.group(2)}/pull/{pr_url_match.group(3)}",
                source="output",
                raw_match=pr_url_match.group(0)
            )
    
    # For gh issue create - look for created issue URL in output
    if pattern_type == "gh_issue_create":
        issue_url_match = OUTPUT_ISSUE_PATTERN.search(output)
        if issue_url_match:
            return ExtractedRef(
                ref_type="issue",
                owner=issue_url_match.group(1),
                repo=issue_url_match.group(2),
                number=int(issue_url_match.group(3)),
                url=f"https://github.com/{issue_url_match.group(1)}/{issue_url_match.group(2)}/issues/{issue_url_match.group(3)}",
                source="output",
                raw_match=issue_url_match.group(0)
            )
    
    # For gh pr merge - check success message
    if pattern_type == "gh_pr_merge":
        merge_match = MERGE_SUCCESS_PATTERN.search(output)
        if merge_match:
            return ExtractedRef(
                ref_type="pr",
                owner=merge_match.group(1),
                repo=merge_match.group(2),
                number=int(merge_match.group(3)),
                url=f"https://github.com/{merge_match.group(1)}/{merge_match.group(2)}/pull/{merge_match.group(3)}",
                source="output",
                raw_match=merge_match.group(0)
            )
    
    # For git push - extract repo from output
    if pattern_type == "git_push":
        repo_match = OUTPUT_REPO_PATTERN.search(output)
        if repo_match:
            return ExtractedRef(
                ref_type="repo",
                owner=repo_match.group(1),
                repo=repo_match.group(2),
                number=None,
                url=f"https://github.com/{repo_match.group(1)}/{repo_match.group(2)}",
                source="output",
                raw_match=repo_match.group(0)
            )
    
    return None


# Command patterns (same as before)
COMMAND_PATTERNS = {
    "git_push": re.compile(r"git\s+push"),
    "gh_pr_create": re.compile(r"gh\s+pr\s+create"),
    "gh_pr_comment": re.compile(r"gh\s+pr\s+comment\s+(\d+)"),
    "gh_pr_review": re.compile(r"gh\s+pr\s+review\s+(\d+)"),
    "gh_pr_merge": re.compile(r"gh\s+pr\s+merge\s+(\d+)"),
    "gh_pr_close": re.compile(r"gh\s+pr\s+close\s+(\d+)"),
    "gh_issue_create": re.compile(r"gh\s+issue\s+create"),
    "gh_issue_comment": re.compile(r"gh\s+issue\s+comment\s+(\d+)"),
    "gh_issue_close": re.compile(r"gh\s+issue\s+close\s+(\d+)"),
}


def extract_refs_from_conversation(conv_dir: Path) -> dict[str, set[str]]:
    """Extract all git URLs from conversation (simplified from cli.py)."""
    refs = {"repos": set(), "prs": set(), "issues": set()}
    
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return refs
    
    pr_pattern = re.compile(r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/pull/(\d+)")
    issue_pattern = re.compile(r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/issues/(\d+)")
    repo_pattern = re.compile(r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)(?:/|$|\.git)")
    
    for event_file in events_dir.glob("event-*.json"):
        try:
            content = event_file.read_text()
            
            for match in pr_pattern.finditer(content):
                url = f"https://github.com/{match.group(1)}/{match.group(2)}/pull/{match.group(3)}"
                refs["prs"].add(url)
            
            for match in issue_pattern.finditer(content):
                url = f"https://github.com/{match.group(1)}/{match.group(2)}/issues/{match.group(3)}"
                refs["issues"].add(url)
            
            for match in repo_pattern.finditer(content):
                # Skip if it's part of a PR or issue URL
                full = match.group(0)
                if "/pull/" not in content[match.start():match.end()+20] and "/issues/" not in content[match.start():match.end()+20]:
                    url = f"https://github.com/{match.group(1)}/{match.group(2)}"
                    refs["repos"].add(url)
                    
        except (json.JSONDecodeError, OSError):
            continue
    
    return refs


def analyze_conversation(conv_dir: Path) -> list[InteractionWithRef]:
    """Analyze a conversation for interactions with ref extraction."""
    interactions = []
    events_dir = conv_dir / "events"
    
    if not events_dir.exists():
        return interactions
    
    # First extract all refs from conversation
    conv_refs = extract_refs_from_conversation(conv_dir)
    
    # Load all events
    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            event = json.loads(event_file.read_text())
            events.append(event)
        except (json.JSONDecodeError, OSError):
            continue
    
    # Scan for command patterns
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
                # Get observation output
                output = ""
                exit_code = None
                if i + 1 < len(events):
                    next_event = events[i + 1]
                    if next_event.get("kind") == "ObservationEvent":
                        obs = next_event.get("observation", {})
                        exit_code = obs.get("exit_code")
                        content = obs.get("content", [])
                        if content and isinstance(content, list):
                            output = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
                
                success = exit_code == 0
                
                # Extract ref from command/output
                extracted_ref = extract_ref_from_command(command, output, pattern_name)
                
                # Check if extracted ref matches any in conversation refs
                matched = False
                if extracted_ref and extracted_ref.url:
                    # Normalize URL (remove .git suffix)
                    norm_url = extracted_ref.url.rstrip("/")
                    if norm_url.endswith(".git"):
                        norm_url = norm_url[:-4]
                    
                    if extracted_ref.ref_type == "pr":
                        matched = norm_url in conv_refs["prs"]
                    elif extracted_ref.ref_type == "issue":
                        matched = norm_url in conv_refs["issues"]
                    elif extracted_ref.ref_type == "repo":
                        # Also check normalized versions of conv_refs
                        norm_repos = {r.rstrip("/").removesuffix(".git") for r in conv_refs["repos"]}
                        matched = norm_url in norm_repos
                
                interaction = InteractionWithRef(
                    conv_id=conv_dir.name,
                    event_id=event.get("id", ""),
                    command=command[:200],
                    pattern_type=pattern_name,
                    success=success,
                    extracted_ref=extracted_ref,
                    output_snippet=output[:300],
                    matched_in_refs=matched,
                )
                interactions.append(interaction)
    
    return interactions


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Analyze correlation between interactions and refs")
    parser.add_argument("--cloud-dir", type=Path, default=Path.home() / ".openhands" / "cloud" / "conversations")
    parser.add_argument("--local-dir", type=Path, default=Path.home() / ".openhands" / "conversations")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--show-unmatched", action="store_true", help="Show interactions that couldn't be matched")
    args = parser.parse_args()
    
    # Collect conversations
    conv_dirs = []
    for base_dir in [args.cloud_dir, args.local_dir]:
        if base_dir.exists():
            conv_dirs.extend(sorted(base_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:args.limit])
    
    print(f"Analyzing {len(conv_dirs)} conversations for ref correlation...")
    
    # Stats
    stats = defaultdict(lambda: {"total": 0, "extracted": 0, "matched": 0, "successful_matched": 0})
    unmatched_examples = []
    
    for conv_dir in conv_dirs[:args.limit]:
        if not conv_dir.is_dir():
            continue
        
        interactions = analyze_conversation(conv_dir)
        
        for interaction in interactions:
            s = stats[interaction.pattern_type]
            s["total"] += 1
            
            if interaction.extracted_ref:
                s["extracted"] += 1
                
                if interaction.matched_in_refs:
                    s["matched"] += 1
                    if interaction.success:
                        s["successful_matched"] += 1
                    
                    if args.verbose:
                        print(f"\n✓ [{interaction.pattern_type}] {interaction.conv_id[:7]}")
                        print(f"  Ref: {interaction.extracted_ref.url}")
                        print(f"  Source: {interaction.extracted_ref.source}")
                else:
                    if args.show_unmatched and len(unmatched_examples) < 20:
                        unmatched_examples.append(interaction)
            else:
                if args.show_unmatched and len(unmatched_examples) < 20:
                    unmatched_examples.append(interaction)
    
    # Summary
    print("\n" + "="*70)
    print("REF CORRELATION ANALYSIS")
    print("="*70)
    
    total_all = sum(s["total"] for s in stats.values())
    extracted_all = sum(s["extracted"] for s in stats.values())
    matched_all = sum(s["matched"] for s in stats.values())
    
    print(f"\n{'Pattern':<20} {'Total':>8} {'Extracted':>10} {'Matched':>10} {'Match Rate':>12}")
    print("-" * 70)
    
    for pattern_type in sorted(stats.keys()):
        s = stats[pattern_type]
        extract_rate = f"{s['extracted']/s['total']*100:.1f}%" if s['total'] else "N/A"
        match_rate = f"{s['matched']/s['extracted']*100:.1f}%" if s['extracted'] else "N/A"
        print(f"{pattern_type:<20} {s['total']:>8} {s['extracted']:>10} {s['matched']:>10} {match_rate:>12}")
    
    print("-" * 70)
    extract_rate = f"{extracted_all/total_all*100:.1f}%" if total_all else "N/A"
    match_rate = f"{matched_all/extracted_all*100:.1f}%" if extracted_all else "N/A"
    print(f"{'TOTAL':<20} {total_all:>8} {extracted_all:>10} {matched_all:>10} {match_rate:>12}")
    
    print(f"\n{'='*70}")
    print("SUMMARY:")
    print(f"  - Ref extraction rate: {extracted_all}/{total_all} = {extract_rate}")
    print(f"  - Match rate (of extracted): {matched_all}/{extracted_all} = {match_rate}")
    print(f"  - Overall correlation: {matched_all}/{total_all} = {matched_all/total_all*100:.1f}%" if total_all else "N/A")
    
    if args.show_unmatched and unmatched_examples:
        print(f"\n{'='*70}")
        print("UNMATCHED/UNEXTRACTED EXAMPLES:")
        for interaction in unmatched_examples[:10]:
            print(f"\n[{interaction.pattern_type}] {interaction.conv_id[:7]}")
            print(f"  Command: {interaction.command[:80]}...")
            if interaction.extracted_ref:
                print(f"  Extracted: {interaction.extracted_ref.raw_match}")
                print(f"  URL: {interaction.extracted_ref.url or 'Could not construct'}")
            else:
                print(f"  Extracted: NONE")
            print(f"  Output: {interaction.output_snippet[:100]}...")


if __name__ == "__main__":
    main()
