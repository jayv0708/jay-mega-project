"""PostgreSQL backed durable Job Broker with SKIP LOCKED."""

from typing import Optional
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import JobStep, JobStepStatus

class JobBroker:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue_step(self, job_id: str | UUID, step_name: str, state_snapshot: dict) -> JobStep:
        step = JobStep(
            job_id=str(job_id),
            step_name=step_name,
            state_snapshot=state_snapshot,
            status=JobStepStatus.pending
        )
        self.session.add(step)
        await self.session.commit()
        return step

    async def dequeue_step(self) -> Optional[JobStep]:
        # SELECT ... FOR UPDATE SKIP LOCKED
        stmt = (
            select(JobStep)
            .where(JobStep.status == JobStepStatus.pending)
            .order_by(JobStep.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        step = result.scalars().first()

        if step:
            step.status = JobStepStatus.running
            await self.session.commit()
            return step
        return None

    async def complete_step(self, step_id: str | UUID, state_snapshot: Optional[dict] = None) -> None:
        stmt = (
            update(JobStep)
            .where(JobStep.id == str(step_id))
            .values(status=JobStepStatus.completed, state_snapshot=state_snapshot)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def fail_step(self, step_id: str | UUID, error_reason: str) -> None:
        stmt = select(JobStep).where(JobStep.id == str(step_id))
        result = await self.session.execute(stmt)
        step = result.scalars().first()
        
        if step:
            step.retry_count += 1
            if step.retry_count >= 3:
                step.status = JobStepStatus.failed
            else:
                step.status = JobStepStatus.pending
            step.error_reason = error_reason
            await self.session.commit()
