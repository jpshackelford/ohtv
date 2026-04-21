"""RAG (Retrieval-Augmented Generation) for answering questions about conversations.

Provides a clean API for:
1. Retrieving relevant context from embeddings
2. Building prompts with context
3. Generating answers using an LLM
"""

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("ohtv")

DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"

DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant that answers questions about software development conversations and coding sessions. 

You have been provided with context from relevant conversation history. Use this context to answer the user's question accurately and concisely.

Guidelines:
- Base your answer on the provided context
- If the context doesn't contain enough information, say so
- Reference specific conversations when relevant
- Be concise but thorough
- Use markdown formatting for code snippets"""


@dataclass
class ContextChunk:
    """A chunk of context retrieved for RAG."""
    conversation_id: str
    title: str
    embed_type: str
    source_text: str
    score: float


@dataclass
class RAGAnswer:
    """Result of a RAG query."""
    answer: str
    context_chunks: list[ContextChunk]
    source_conversation_ids: set[str]
    search_time_seconds: float
    generation_time_seconds: float
    model: str


class RAGAnswerer:
    """Answers questions using retrieval-augmented generation.
    
    Uses embeddings to find relevant context from conversations,
    then generates an answer using an LLM.
    """
    
    def __init__(
        self,
        embed_store,
        conv_store,
        model: str | None = None,
        system_prompt: str | None = None,
    ):
        """Initialize RAG answerer.
        
        Args:
            embed_store: EmbeddingStore for retrieving context
            conv_store: ConversationStore for conversation metadata
            model: LLM model for generation (default: LLM_MODEL env var or gpt-4o-mini)
            system_prompt: Custom system prompt (default: built-in prompt)
        """
        self.embed_store = embed_store
        self.conv_store = conv_store
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    
    def answer_question(
        self,
        question: str,
        max_context_chunks: int = 5,
        min_score: float = 0.3,
    ) -> RAGAnswer:
        """Answer a question using RAG.
        
        Args:
            question: The question to answer
            max_context_chunks: Maximum number of context chunks to retrieve
            min_score: Minimum similarity score for context (0-1)
        
        Returns:
            RAGAnswer with the generated answer and metadata
        
        Raises:
            RuntimeError: If LLM configuration is missing or API call fails
            ValueError: If no relevant context is found
        """
        import time
        
        # Retrieve context
        start_time = time.perf_counter()
        context_chunks = self._retrieve_context(question, max_context_chunks, min_score)
        search_time = time.perf_counter() - start_time
        
        if not context_chunks:
            raise ValueError("No relevant context found for the question")
        
        # Generate answer
        gen_start = time.perf_counter()
        answer = self._generate_answer(question, context_chunks)
        gen_time = time.perf_counter() - gen_start
        
        source_ids = {c.conversation_id for c in context_chunks}
        
        return RAGAnswer(
            answer=answer,
            context_chunks=context_chunks,
            source_conversation_ids=source_ids,
            search_time_seconds=search_time,
            generation_time_seconds=gen_time,
            model=self.model,
        )
    
    def _retrieve_context(
        self,
        question: str,
        max_chunks: int,
        min_score: float,
    ) -> list[ContextChunk]:
        """Retrieve relevant context chunks for a question."""
        from ohtv.analysis.embeddings import get_embedding
        
        # Embed the question
        query_result = get_embedding(question)
        query_embedding = query_result.embedding
        
        # Search for relevant context
        results = self.embed_store.get_context_for_rag(
            query_embedding,
            max_chunks=max_chunks,
            min_score=min_score,
        )
        
        # Convert to ContextChunk with conversation titles
        chunks = []
        for r in results:
            conv = self.conv_store.get(r.conversation_id)
            title = conv.title if conv and conv.title else f"Conversation {r.conversation_id[:8]}"
            
            chunks.append(ContextChunk(
                conversation_id=r.conversation_id,
                title=title,
                embed_type=r.embed_type,
                source_text=r.source_text,
                score=r.score,
            ))
        
        return chunks
    
    def _generate_answer(
        self,
        question: str,
        context_chunks: list[ContextChunk],
    ) -> str:
        """Generate an answer using the LLM."""
        import litellm
        
        api_key = os.environ.get("LLM_API_KEY")
        api_base = os.environ.get("LLM_BASE_URL")
        
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY environment variable not set. "
                "This is required for answer generation."
            )
        
        # Build context text
        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            context_parts.append(f"[Source {i}: {chunk.title} ({chunk.embed_type})]")
            context_parts.append(chunk.source_text)
            context_parts.append("")
        
        context_text = "\n".join(context_parts)
        
        user_prompt = f"""Context from conversation history:
{context_text}

Question: {question}

Please provide a helpful answer based on the context above."""
        
        try:
            response = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                api_key=api_key,
                api_base=api_base,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"LLM API call failed: {e}") from e
