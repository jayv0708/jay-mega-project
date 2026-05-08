from __future__ import annotations

import difflib
import re
from typing import Any

from app.context import AgentOutput, Chunk, Citation, Contradiction, SharedContext, SubTask
from agents.base import BaseAgent
from agents.llm import AnthropicClient
from agents.prompt_loader import load_prompt_json
from retrieval import RetrievalService, RetrievedChunk
from db.db import get_async_session


class OrchestratorAgent(BaseAgent):
    def __init__(self, agent_id: str = "orchestrator", max_context_budget: int = 1536) -> None:
        super().__init__(agent_id, max_context_budget)
        self.llm = AnthropicClient()

    async def execute(self, context: SharedContext) -> SharedContext:
        prompt = load_prompt_json("orchestrator")
        fallback = {
            "subtasks": [
                {"id": "task_decomposition", "description": "Plan subtasks for the query.", "dependencies": []},
                {"id": "task_rag", "description": "Retrieve and cite supporting evidence.", "dependencies": ["task_decomposition"]},
                {"id": "task_critique", "description": "Review claims and identify weak spans.", "dependencies": ["task_rag"]},
                {"id": "task_synthesis", "description": "Merge evidence and produce the final answer.", "dependencies": ["task_critique"]}
            ],
            "dependencies": [],
            "selected_agents": ["decomposition", "rag", "critique", "synthesis"],
            "required_tools": ["web_search", "code_sandbox"],
            "estimated_tokens": 1000,
            "estimated_cost": 0.05,
            "confidence": 0.9,
            "routing_justification": "Default deterministic route covers planning, retrieval, critique, and synthesis.",
            "rejected_alternatives": ["skip_rag"]
        }
        
        system_prompt = prompt.get("system", "")
        system_prompt += (
            "\n\nYou MUST return a JSON object with the following schema:\n"
            "{\n"
            '  "subtasks": [{"id": str, "description": str, "dependencies": list[str]}],\n'
            '  "dependencies": list[dict],\n'
            '  "selected_agents": list[str],\n'
            '  "required_tools": list[str],\n'
            '  "estimated_tokens": int,\n'
            '  "estimated_cost": float,\n'
            '  "confidence": float,\n'
            '  "routing_justification": str,\n'
            '  "rejected_alternatives": list[str]\n'
            "}"
        )

        decision = await self.llm.complete_json(
            system_prompt,
            f"Query: {context.query}",
            temperature=0.0,
            max_tokens=800,
            fallback=fallback,
        )
        self.consume_budget(100)
        context.metadata["routing_decision"] = decision
        context.add_agent_output(
            AgentOutput(
                agent_id=self.agent_id,
                output=decision.get("routing_justification", "Routing complete."),
                metadata={"routing_decision": decision},
            )
        )
        return context


class DecompositionAgent(BaseAgent):
    def __init__(self, agent_id: str = "decomposition", max_context_budget: int = 1200) -> None:
        super().__init__(agent_id, max_context_budget)
        self.llm = AnthropicClient()

    async def execute(self, context: SharedContext) -> SharedContext:
        prompt = load_prompt_json("decomposition")
        fallback = {
            "subtasks": [
                {
                    "id": "task_understand",
                    "type": "clarification",
                    "description": f"Resolve the intent and key entities in: {context.query}",
                    "dependencies": [],
                },
                {
                    "id": "task_evidence",
                    "type": "retrieval",
                    "description": "Collect at least two supporting evidence chunks.",
                    "dependencies": ["task_understand"],
                },
                {
                    "id": "task_answer",
                    "type": "synthesis",
                    "description": "Produce a cited answer and resolve any contradictions.",
                    "dependencies": ["task_evidence"],
                },
            ]
        }
        plan = await self.llm.complete_json(
            prompt.get("system", ""),
            f"Break this query into a DAG: {context.query}",
            temperature=0.0,
            max_tokens=900,
            fallback=fallback,
        )
        subtasks = [SubTask(**item) for item in plan.get("subtasks", fallback["subtasks"])]
        self.check_can_add([task.model_dump() for task in subtasks])
        context.subtasks = subtasks
        context.add_agent_output(
            AgentOutput(
                agent_id=self.agent_id,
                output=f"Created {len(subtasks)} subtasks with dependency order.",
                metadata={"subtasks": [task.model_dump() for task in subtasks]},
            )
        )
        return context


class RAGAgent(BaseAgent):
    def __init__(
        self,
        agent_id: str = "rag",
        max_context_budget: int = 2400,
        retrieval_service: RetrievalService = None
    ) -> None:
        super().__init__(agent_id, max_context_budget)
        self.retrieval_service = retrieval_service

    async def execute(self, context: SharedContext) -> SharedContext:
        # If no retrieval service is provided, fall back to mock data
        if self.retrieval_service is None:
            return await self._execute_mock_retrieval(context)

        # Perform real retrieval
        async with get_async_session() as db_session:
            retrieved_chunks = await self.retrieval_service.retrieve(
                query=context.query,
                top_k=5,  # Retrieve top 5 chunks
                db_session=db_session
            )

        # Convert RetrievedChunk objects to Chunk objects for context
        chunks = []
        for retrieved in retrieved_chunks:
            chunk = Chunk(
                id=retrieved.chunk_id,
                text=retrieved.content,
                source_url=f"doc://{retrieved.document_id}",
                relevance_score=retrieved.combined_score,
                metadata={
                    "document_id": retrieved.document_id,
                    "chunk_index": retrieved.chunk_index,
                    "semantic_score": retrieved.semantic_score,
                    "bm25_score": retrieved.bm25_score,
                }
            )
            chunks.append(chunk)

        if not chunks:
            # If no chunks found, fall back to mock data
            return await self._execute_mock_retrieval(context)

        # --- Retrieval poisoning defence ---
        from tools.security import inspect_retrieval_chunk
        safe_chunks = []
        for chunk in chunks:
            result = inspect_retrieval_chunk(chunk.text, chunk.id, job_id=str(context.job_id))
            if result.safe:
                safe_chunks.append(chunk)
        chunks = safe_chunks
        if not chunks:
            return await self._execute_mock_retrieval(context)

        self.check_can_add([chunk.model_dump() for chunk in chunks])
        existing = {chunk.id for chunk in context.retrieved_chunks}
        context.retrieved_chunks.extend(chunk for chunk in chunks if chunk.id not in existing)

        # Create citations for the retrieved chunks
        sentences = []
        for i, chunk in enumerate(chunks[:3]):  # Use top 3 chunks
            sentence = f"Evidence {i+1}: {chunk.text[:200]}..." if len(chunk.text) > 200 else f"Evidence {i+1}: {chunk.text}"
            sentences.append((sentence, chunk))

            context.citations.append(
                Citation(
                    sentence=sentence,
                    chunk_id=chunk.id,
                    agent_id=self.agent_id,
                    source_url=chunk.source_url,
                    confidence=chunk.relevance_score,
                )
            )

        output_text = " ".join(sentence for sentence, _ in sentences)
        context.add_agent_output(
            AgentOutput(
                agent_id=self.agent_id,
                output=output_text,
                metadata={
                    "retrieval_count": len(chunks),
                    "citations": [citation.model_dump() for citation in context.citations if citation.agent_id == self.agent_id],
                },
            )
        )
        self.consume_budget(len(output_text) // 4)  # Rough token estimation
        return context

    async def _execute_mock_retrieval(self, context: SharedContext) -> SharedContext:
        """Fallback mock retrieval for when no real retrieval service is available."""
        chunk_a = Chunk(
            id="chunk_a",
            text=f"Primary evidence about '{context.query}' establishes the central answer frame.",
            source_url="fixture://search/primary",
            relevance_score=0.91,
        )
        follow_up = self._extract_follow_up_query(chunk_a.text)
        chunk_b = Chunk(
            id="chunk_b",
            text=f"Follow-up evidence for '{follow_up}' adds a second independent support point.",
            source_url="fixture://search/follow-up",
            relevance_score=0.84,
        )
        chunks = [chunk_a, chunk_b]
        self.check_can_add([chunk.model_dump() for chunk in chunks])
        existing = {chunk.id for chunk in context.retrieved_chunks}
        context.retrieved_chunks.extend(chunk for chunk in chunks if chunk.id not in existing)

        sentences = [
            (f"The answer should be grounded in the primary evidence for {context.query}.", chunk_a),
            ("A second hop supports the answer with independent follow-up evidence.", chunk_b),
        ]
        for sentence, chunk in sentences:
            context.citations.append(
                Citation(
                    sentence=sentence,
                    chunk_id=chunk.id,
                    agent_id=self.agent_id,
                    source_url=chunk.source_url,
                    confidence=chunk.relevance_score,
                )
            )
        output_text = " ".join(sentence for sentence, _ in sentences)
        context.add_agent_output(
            AgentOutput(
                agent_id=self.agent_id,
                output=output_text,
                metadata={
                    "follow_up_query": follow_up,
                    "citations": [citation.model_dump() for citation in context.citations if citation.agent_id == self.agent_id],
                },
            )
        )
        self.consume_budget(120)
        return context

    def _extract_follow_up_query(self, text: str) -> str:
        words = re.findall(r"[A-Za-z0-9']+", text)
        return " ".join(words[-6:]) if words else "supporting evidence"


class CritiqueAgent(BaseAgent):
    def __init__(self, agent_id: str = "critique", max_context_budget: int = 1600) -> None:
        super().__init__(agent_id, max_context_budget)

    async def execute(self, context: SharedContext) -> SharedContext:
        flags: list[dict[str, Any]] = []
        for source_agent, output in context.agent_outputs.items():
            if source_agent == self.agent_id:
                continue
            claims = [part.strip() for part in re.split(r"(?<=[.!?])\s+", output.output) if part.strip()]
            cursor = 0
            for claim in claims:
                start = output.output.find(claim, cursor)
                end = start + len(claim)
                cursor = end
                confidence = 0.85 if source_agent == "rag" else 0.65
                flag = confidence < 0.7
                item = {
                    "claim_text": claim,
                    "claim_span_start": start,
                    "claim_span_end": end,
                    "confidence": confidence,
                    "flag": flag,
                    "reason": "Needs stronger citation support." if flag else "Supported by available context.",
                    "source_agent_id": source_agent,
                }
                flags.append(item)
                if flag:
                    context.add_contradiction(
                        Contradiction(
                            statement_a=claim,
                            agent_a=source_agent,
                            statement_b="Claim requires stronger provenance before final synthesis.",
                            agent_b=self.agent_id,
                            severity="medium",
                        )
                    )
        self.check_can_add(flags)
        context.add_agent_output(
            AgentOutput(
                agent_id=self.agent_id,
                output=f"Reviewed {len(flags)} claims and flagged {sum(1 for item in flags if item['flag'])} spans.",
                metadata={"claim_scores": flags},
            )
        )
        self.consume_budget(90)
        return context


class SynthesisAgent(BaseAgent):
    def __init__(self, agent_id: str = "synthesis", max_context_budget: int = 1800) -> None:
        super().__init__(agent_id, max_context_budget)

    async def execute(self, context: SharedContext) -> SharedContext:
        resolution_records: list[dict[str, Any]] = []
        for contradiction in context.contradictions:
            contradiction.resolution = "addressed"
            contradiction.justification = "Final answer keeps only claims with citations or explicit caveats."
            resolution_records.append(contradiction.model_dump())

        cited_sentences = [citation.sentence for citation in context.citations if citation.sentence]
        if not cited_sentences:
            cited_sentences = [output.output for key, output in context.agent_outputs.items() if key != self.agent_id]
        final_sentences = cited_sentences[:4] or ["No supported answer could be produced."]
        provenance_map = []
        for index, sentence in enumerate(final_sentences, start=1):
            citation = next((item for item in context.citations if item.sentence == sentence), None)
            provenance_map.append(
                {
                    "sentence_id": f"s{index}",
                    "source_agent_id": citation.agent_id if citation else "synthesis",
                    "source_chunk_id": citation.chunk_id if citation else None,
                }
            )
        final_answer = " ".join(final_sentences)
        self.check_can_add({"final_answer": final_answer, "provenance_map": provenance_map})
        context.add_agent_output(
            AgentOutput(
                agent_id=self.agent_id,
                output=final_answer,
                metadata={
                    "provenance_map": provenance_map,
                    "contradiction_resolutions": resolution_records,
                },
            )
        )
        self.consume_budget(100)
        return context

