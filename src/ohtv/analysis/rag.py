"""RAG (Retrieval-Augmented Generation) for answering questions about conversations.

Provides a clean API for:
1. Retrieving relevant context from embeddings
2. Building prompts with context including refs for disambiguation
3. Generating answers using an LLM
4. Temporal filtering based on question intent
5. Citation output with conversation URLs, dates, and summaries
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import litellm

# Suppress LiteLLM info messages that spam output during batch operations
litellm.suppress_debug_info = True

log = logging.getLogger("ohtv")

DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"

# Cloud conversations have 14-day retention
CLOUD_RETENTION_DAYS = 14

DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant that answers questions about software development conversations and coding sessions.

You have been provided with context from relevant conversation history. Each source includes:
- Title and date
- Summary (when available)
- Related refs (PRs, issues, repos) - use these to disambiguate references like "#42"

Guidelines:
- Base your answer on the provided context
- When citing information, reference the specific conversation by title (e.g., "In the conversation 'Configure MCP secrets' from 3 days ago...")
- Use the provided refs to accurately cite PRs/issues (e.g., "jpshackelford/ohtv#42" not just "#42")
- If multiple conversations are relevant, mention them
- If the context doesn't contain enough information, say so clearly
- Be concise but thorough
- Use markdown formatting for code snippets"""


@dataclass
class RefInfo:
    """A reference (PR/issue) associated with a conversation."""
    ref_type: str  # "pr" or "issue"
    url: str
    fqn: str  # e.g., "owner/repo#123"
    display_name: str  # e.g., "repo #123"
    link_type: str  # "read" or "write"


@dataclass 
class RepoInfo:
    """A repository associated with a conversation."""
    url: str
    fqn: str  # e.g., "owner/repo"
    short_name: str
    link_type: str  # "read" or "write"


@dataclass
class ConversationSource:
    """Full source information for a conversation."""
    conversation_id: str
    title: str
    summary: str | None = None
    source: str = "local"  # "local" or "cloud"
    cloud_url: str | None = None
    created_at: datetime | None = None
    repos: list[RepoInfo] = field(default_factory=list)
    prs: list[RefInfo] = field(default_factory=list)
    issues: list[RefInfo] = field(default_factory=list)
    
    def is_cloud_url_valid(self) -> bool:
        """Check if cloud URL is valid (within 14-day retention)."""
        if self.source != "cloud" or not self.created_at:
            return False
        now = datetime.now(timezone.utc)
        if self.created_at.tzinfo is None:
            created = self.created_at.replace(tzinfo=timezone.utc)
        else:
            created = self.created_at
        return (now - created).days <= CLOUD_RETENTION_DAYS


@dataclass
class ContextChunk:
    """A chunk of context retrieved for RAG."""
    conversation_id: str
    title: str
    embed_type: str
    source_text: str
    score: float
    chunk_index: int = 0  # For ordering chunks within a conversation
    # New fields for citations
    summary: str | None = None
    cloud_url: str | None = None
    created_at: datetime | None = None
    conv_source: str = "local"  # "local" or "cloud"
    source: ConversationSource | None = None
    
    @property
    def display_url(self) -> str | None:
        """Get URL to display (only if cloud and within 14-day retention)."""
        if self.source and self.source.is_cloud_url_valid():
            return self.cloud_url
        return None


@dataclass
class RAGAnswer:
    """Result of a RAG query."""
    answer: str
    context_chunks: list[ContextChunk]
    source_conversation_ids: set[str]
    search_time_seconds: float
    generation_time_seconds: float
    model: str
    temporal_filter_applied: bool = False
    date_range: tuple[datetime | None, datetime | None] | None = None
    # Aggregated refs from all source conversations
    related_repos: list[RepoInfo] | None = None
    related_prs: list[RefInfo] | None = None
    related_issues: list[RefInfo] | None = None
    # Token counts and cost
    context_tokens: int = 0
    total_tokens: int = 0  # Context + question + system prompt
    cost: float = 0.0  # Estimated cost in USD


class RAGAnswerer:
    """Answers questions using retrieval-augmented generation.
    
    Uses embeddings to find relevant context from conversations,
    then generates an answer using an LLM. Supports automatic
    temporal filtering based on question intent.
    
    Enhanced with:
    - Full source metadata (dates, summaries, cloud URLs)
    - Related refs (PRs, issues, repos) for disambiguation
    - Aggregated "See Also" refs from all source conversations
    """
    
    def __init__(
        self,
        embed_store,
        conv_store,
        model: str | None = None,
        system_prompt: str | None = None,
        enable_temporal_filter: bool = True,
        link_store=None,
        ref_store=None,
        repo_store=None,
        cloud_base_url: str | None = None,
    ):
        """Initialize RAG answerer.
        
        Args:
            embed_store: EmbeddingStore for retrieving context
            conv_store: ConversationStore for conversation metadata
            model: LLM model for generation (default: LLM_MODEL env var or gpt-4o-mini)
            system_prompt: Custom system prompt (default: built-in prompt)
            enable_temporal_filter: Enable automatic temporal filtering from questions
            link_store: LinkStore for conversation-ref relationships (optional)
            ref_store: ReferenceStore for ref details (optional)
            repo_store: RepoStore for repository details (optional)
            cloud_base_url: Base URL for cloud conversations (default: env or app.all-hands.dev)
        """
        self.embed_store = embed_store
        self.conv_store = conv_store
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.enable_temporal_filter = enable_temporal_filter
        self.link_store = link_store
        self.ref_store = ref_store
        self.repo_store = repo_store
        self.cloud_base_url = cloud_base_url or os.environ.get(
            "OHTV_CLOUD_API_URL", "https://app.all-hands.dev"
        )
    
    def answer_question(
        self,
        question: str,
        max_context_chunks: int = 5,
        min_score: float = 0.3,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> RAGAnswer:
        """Answer a question using RAG.
        
        Args:
            question: The question to answer
            max_context_chunks: Maximum number of context chunks to retrieve
            min_score: Minimum similarity score for context (0-1)
            start_date: Override: only include conversations from this date
            end_date: Override: only include conversations until this date
        
        Returns:
            RAGAnswer with the generated answer and metadata
        
        Raises:
            RuntimeError: If LLM configuration is missing or API call fails
            ValueError: If no relevant context is found
        """
        import time
        
        # Extract temporal filter if enabled and no explicit dates provided
        temporal_applied = False
        search_query = question
        
        if self.enable_temporal_filter and start_date is None and end_date is None:
            from ohtv.analysis.temporal import extract_temporal_filter
            temporal = extract_temporal_filter(question)
            if temporal.has_temporal_intent:
                start_date = temporal.start_date
                end_date = temporal.end_date
                search_query = temporal.cleaned_query
                temporal_applied = True
                log.debug(
                    "Temporal filter extracted: %s to %s, query: %s",
                    start_date, end_date, search_query
                )
        
        # Retrieve context
        start_time = time.perf_counter()
        context_chunks = self._retrieve_context(
            search_query, max_context_chunks, min_score, start_date, end_date
        )
        search_time = time.perf_counter() - start_time
        
        if not context_chunks:
            # If temporal filter found nothing, try without filter
            if temporal_applied:
                log.debug("No results with temporal filter, retrying without filter")
                context_chunks = self._retrieve_context(
                    question, max_context_chunks, min_score, None, None
                )
                if context_chunks:
                    temporal_applied = False
                    start_date = None
                    end_date = None
        
        if not context_chunks:
            raise ValueError("No relevant context found for the question")
        
        # Generate answer
        gen_start = time.perf_counter()
        answer, context_tokens, total_tokens, cost = self._generate_answer(question, context_chunks)
        gen_time = time.perf_counter() - gen_start
        
        source_ids = {c.conversation_id for c in context_chunks}
        
        # Aggregate refs from all source conversations
        all_repos: dict[str, RepoInfo] = {}
        all_prs: dict[str, RefInfo] = {}
        all_issues: dict[str, RefInfo] = {}
        
        for chunk in context_chunks:
            if chunk.source:
                for repo in chunk.source.repos:
                    if repo.url not in all_repos:
                        all_repos[repo.url] = repo
                for pr in chunk.source.prs:
                    if pr.url not in all_prs:
                        all_prs[pr.url] = pr
                for issue in chunk.source.issues:
                    if issue.url not in all_issues:
                        all_issues[issue.url] = issue
        
        return RAGAnswer(
            answer=answer,
            context_chunks=context_chunks,
            source_conversation_ids=source_ids,
            search_time_seconds=search_time,
            generation_time_seconds=gen_time,
            model=self.model,
            temporal_filter_applied=temporal_applied,
            date_range=(start_date, end_date) if temporal_applied else None,
            related_repos=list(all_repos.values()) if all_repos else None,
            related_prs=list(all_prs.values()) if all_prs else None,
            related_issues=list(all_issues.values()) if all_issues else None,
            context_tokens=context_tokens,
            total_tokens=total_tokens,
            cost=cost,
        )
    
    def _retrieve_context(
        self,
        question: str,
        max_chunks: int,
        min_score: float,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[ContextChunk]:
        """Retrieve relevant context chunks for a question with full metadata."""
        from ohtv.analysis.embeddings import get_embedding
        
        # Embed the question
        query_result = get_embedding(question)
        query_embedding = query_result.embedding
        
        # Search for relevant context with optional date filter
        results = self.embed_store.get_context_for_rag(
            query_embedding,
            max_chunks=max_chunks,
            min_score=min_score,
            start_date=start_date,
            end_date=end_date,
        )
        
        # Convert to ContextChunk with full metadata
        chunks = []
        for r in results:
            conv = self.conv_store.get(r.conversation_id)
            title = conv.title if conv and conv.title else f"Conversation {r.conversation_id[:8]}"
            created_at = conv.created_at if conv else None
            summary = conv.summary if conv else None
            conv_source = conv.source if conv else "local"
            
            # Get source info with refs
            source = self._get_conversation_source(r.conversation_id)
            cloud_url = self._get_cloud_url(r.conversation_id)
            
            chunks.append(ContextChunk(
                conversation_id=r.conversation_id,
                title=title,
                embed_type=r.embed_type,
                source_text=r.source_text,
                score=r.score,
                chunk_index=r.chunk_index,
                summary=summary,
                cloud_url=cloud_url,
                created_at=created_at,
                conv_source=conv_source or "local",
                source=source,
            ))
        
        # Sort chunks: group by conversation, then by embed_type, then by chunk_index
        # This ensures the LLM sees coherent context from each conversation
        chunks.sort(key=lambda c: (c.conversation_id, c.embed_type, c.chunk_index))
        
        return chunks
    
    def _get_cloud_url(self, conversation_id: str) -> str:
        """Generate the cloud URL for a conversation."""
        return f"{self.cloud_base_url}/conversations/{conversation_id}"
    
    def _get_conversation_source(self, conversation_id: str) -> ConversationSource | None:
        """Get full source information including refs for a conversation."""
        if not all([self.link_store, self.ref_store, self.repo_store]):
            return None
        
        try:
            # Get conversation metadata
            conv = self.conv_store.get(conversation_id)
            title = conv.title if conv and conv.title else f"Conversation {conversation_id[:8]}"
            created_at = conv.created_at if conv else None
            summary = conv.summary if conv else None
            conv_source = conv.source if conv else "local"
            
            # Get repos
            repos = []
            for repo_id, link_type in self.link_store.get_repos_for_conversation(conversation_id):
                repo = self.repo_store.get_by_id(repo_id)
                if repo:
                    repos.append(RepoInfo(
                        url=repo.canonical_url,
                        fqn=repo.fqn,
                        short_name=repo.short_name,
                        link_type=link_type.value,
                    ))
            
            # Get PRs and issues
            prs = []
            issues = []
            for ref_id, link_type in self.link_store.get_refs_for_conversation(conversation_id):
                ref = self.ref_store.get_by_id(ref_id)
                if ref:
                    ref_info = RefInfo(
                        ref_type=ref.ref_type.value,
                        url=ref.url,
                        fqn=ref.fqn,
                        display_name=ref.display_name,
                        link_type=link_type.value,
                    )
                    if ref.ref_type.value == "pull_request":
                        prs.append(ref_info)
                    else:
                        issues.append(ref_info)
            
            return ConversationSource(
                conversation_id=conversation_id,
                title=title,
                summary=summary,
                source=conv_source or "local",
                cloud_url=self._get_cloud_url(conversation_id),
                created_at=created_at,
                repos=repos,
                prs=prs,
                issues=issues,
            )
        except Exception as e:
            log.debug("Error getting source info for %s: %s", conversation_id, e)
            return None
    
    def _generate_answer(
        self,
        question: str,
        context_chunks: list[ContextChunk],
    ) -> tuple[str, int, int, float]:
        """Generate an answer using the LLM with rich context.
        
        Returns:
            Tuple of (answer, context_tokens, total_input_tokens, cost)
        """
        api_key = os.environ.get("LLM_API_KEY")
        api_base = os.environ.get("LLM_BASE_URL")
        
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY environment variable not set. "
                "This is required for answer generation."
            )
        
        # Build context text with richer metadata for LLM
        # Sort by score descending so most relevant sources come first
        sorted_chunks = sorted(context_chunks, key=lambda c: c.score, reverse=True)
        
        context_parts = []
        for i, chunk in enumerate(sorted_chunks, 1):
            # Header with title, date, and relevance score
            header = f"[Source {i}: {chunk.title}"
            if chunk.created_at:
                age = self._format_age(chunk.created_at)
                header += f" ({age})"
            header += f" - relevance: {chunk.score:.0%}]"
            context_parts.append(header)
            
            # Summary (if available)
            if chunk.summary:
                context_parts.append(f"Summary: {chunk.summary}")
            
            # Related refs for disambiguation
            if chunk.source:
                ref_fqns = []
                for pr in chunk.source.prs[:3]:  # Limit to avoid bloat
                    ref_fqns.append(f"PR {pr.fqn}")
                for issue in chunk.source.issues[:3]:
                    ref_fqns.append(f"Issue {issue.fqn}")
                for repo in chunk.source.repos[:2]:
                    ref_fqns.append(f"Repo {repo.fqn}")
                if ref_fqns:
                    context_parts.append(f"Related: {', '.join(ref_fqns)}")
            
            # Content
            context_parts.append(chunk.source_text)
            context_parts.append("")
        
        context_text = "\n".join(context_parts)
        
        user_prompt = f"""Context from conversation history:
{context_text}

Question: {question}

Please provide a helpful answer based on the context above."""
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        # Estimate token counts (approximate using litellm's token counter)
        try:
            context_tokens = litellm.token_counter(model=self.model, text=context_text)
            total_tokens = litellm.token_counter(model=self.model, messages=messages)
        except Exception:
            # Fallback: rough estimate of ~4 chars per token
            context_tokens = len(context_text) // 4
            total_tokens = (len(self.system_prompt) + len(user_prompt)) // 4
        
        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                api_key=api_key,
                api_base=api_base,
            )
            
            # Calculate cost using litellm's completion_cost
            cost = 0.0
            try:
                cost = litellm.completion_cost(completion_response=response)
            except Exception:
                # Fallback: rough estimate if model not in litellm's pricing
                pass
            
            return response.choices[0].message.content, context_tokens, total_tokens, cost
        except Exception as e:
            raise RuntimeError(f"LLM API call failed: {e}") from e
    
    def _format_age(self, dt: datetime) -> str:
        """Format datetime as relative age (e.g., '3 days ago')."""
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        
        if delta.days == 0:
            return "today"
        elif delta.days == 1:
            return "yesterday"
        elif delta.days < 7:
            return f"{delta.days} days ago"
        elif delta.days < 30:
            weeks = delta.days // 7
            return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        else:
            months = delta.days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
