"""
econode – DAG Workflow Scheduler
Extends econode to handle interdependent task graphs (DAGs) with deadline constraints.
Inspired by CaWoSched (arXiv:2507.08725, KIT-EAE) which demonstrated significant
carbon savings using greedy + local-search heuristics across 16 algorithm variants.

Our approach: a lean CriticalPath-first heuristic that:
1. Validates the DAG for cycles
2. Computes critical path to identify deadline pressure per task
3. Assigns slack-weighted SOAD scores to each task in topological order
4. Respects precedence constraints — a task waits for all parents to complete
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

log = logging.getLogger(__name__)


# ── Task Node ─────────────────────────────────────────────────────────────────

@dataclass
class TaskNode:
    """A single task within a DAG workflow."""
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    gpu_count: int = 1
    duration_hours: float = 1.0
    cost_weight: float = 0.6
    carbon_weight: float = 0.4
    # Set by the scheduler after placement
    assigned_region_id: Optional[str] = None
    status: str = "PENDING"   # PENDING | READY | RUNNING | DONE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # Runtime metrics
    actual_cost_usd: float = 0.0
    actual_carbon_kgco2: float = 0.0

    @property
    def is_done(self) -> bool:
        return self.status == "DONE"

    @property
    def is_ready(self) -> bool:
        return self.status == "READY"


# ── DAG Workflow ──────────────────────────────────────────────────────────────

class WorkflowDAG:
    """
    Directed Acyclic Graph of TaskNodes.
    Edge (A → B) means B depends on A (B cannot start until A is done).

    CaWoSched insight: handling task precedence cuts wasted idle time and
    avoids scheduling a dependent task in a clean-energy window that its
    parent task won't reach in time.
    """

    def __init__(self, name: str, deadline_hours: float, budget_usd: float) -> None:
        self.id          = str(uuid4())
        self.name        = name
        self.deadline_hours = deadline_hours
        self.budget_usd  = budget_usd
        self.created_at  = datetime.now(timezone.utc)
        self._nodes: dict[str, TaskNode] = {}
        self._edges: dict[str, set[str]] = defaultdict(set)  # parent_id → {child_ids}
        self._parents: dict[str, set[str]] = defaultdict(set) # child_id  → {parent_ids}

    # ── Graph Construction ────────────────────────────────────────────────────

    def add_task(self, task: TaskNode) -> "WorkflowDAG":
        self._nodes[task.id] = task
        return self

    def add_dependency(self, parent_id: str, child_id: str) -> "WorkflowDAG":
        """Declare that `child_id` depends on `parent_id`."""
        if parent_id not in self._nodes or child_id not in self._nodes:
            raise ValueError(f"Unknown task id in dependency: {parent_id} → {child_id}")
        self._edges[parent_id].add(child_id)
        self._parents[child_id].add(parent_id)
        if self._has_cycle():
            self._edges[parent_id].discard(child_id)
            self._parents[child_id].discard(parent_id)
            raise ValueError(f"Adding {parent_id} → {child_id} creates a cycle")
        return self

    # ── Scheduling Interface ──────────────────────────────────────────────────

    def topological_order(self) -> list[TaskNode]:
        """Kahn's algorithm — returns tasks in valid execution order."""
        in_degree = {nid: len(parents) for nid, parents in self._parents.items()}
        for nid in self._nodes:
            in_degree.setdefault(nid, 0)
        queue: deque[str] = deque(nid for nid, d in in_degree.items() if d == 0)
        order: list[TaskNode] = []
        while queue:
            nid = queue.popleft()
            order.append(self._nodes[nid])
            for child_id in self._edges.get(nid, set()):
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)
        if len(order) != len(self._nodes):
            raise RuntimeError("DAG contains a cycle — cannot produce topological order")
        return order

    def ready_tasks(self) -> list[TaskNode]:
        """Tasks whose all parents are done and which are still PENDING."""
        result = []
        for task in self._nodes.values():
            if task.status != "PENDING":
                continue
            parents_done = all(
                self._nodes[pid].is_done for pid in self._parents.get(task.id, set())
            )
            if parents_done:
                task.status = "READY"
                result.append(task)
        return result

    def critical_path_hours(self) -> float:
        """
        Longest path through the DAG (in hours).
        Used to compute per-task scheduling slack:
          slack = deadline_hours - (critical_path_remaining - task_duration)
        """
        longest: dict[str, float] = {}
        for task in self.topological_order():
            parent_max = max(
                (longest.get(pid, 0.0) for pid in self._parents.get(task.id, set())),
                default=0.0,
            )
            longest[task.id] = parent_max + task.duration_hours
        return max(longest.values(), default=0.0)

    def task_slack(self, task_id: str) -> float:
        """
        Hours of scheduling slack for a specific task.
        Zero or negative → deadline pressure, force immediate placement.
        """
        cp = self.critical_path_hours()
        task = self._nodes[task_id]
        # Estimate how much of the critical path is before this task
        elapsed_cp = cp - task.duration_hours
        return max(0.0, self.deadline_hours - elapsed_cp)

    # ── Metrics ───────────────────────────────────────────────────────────────

    @property
    def total_cost_usd(self) -> float:
        return sum(t.actual_cost_usd for t in self._nodes.values())

    @property
    def total_carbon_kgco2(self) -> float:
        return sum(t.actual_carbon_kgco2 for t in self._nodes.values())

    @property
    def is_complete(self) -> bool:
        return all(t.is_done for t in self._nodes.values())

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def status_summary(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for t in self._nodes.values():
            counts[t.status] += 1
        return dict(counts)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _has_cycle(self) -> bool:
        visited: set[str] = set()
        rec_stack: set[str] = set()
        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for child in self._edges.get(node_id, set()):
                if child not in visited:
                    if dfs(child):
                        return True
                elif child in rec_stack:
                    return True
            rec_stack.discard(node_id)
            return False
        return any(dfs(nid) for nid in self._nodes if nid not in visited)


# ── DAG Optimizer Integration ────────────────────────────────────────────────

class DAGScheduler:
    """
    Wraps econodeOptimizer to schedule each ready task in a DAG.
    Applies CaWoSched's precedence-aware greedy heuristic:
      - Tasks with zero slack get forced immediate start
      - Tasks with slack use the SOAD optimizer with offset from slack budget
    """

    def __init__(self, optimizer, snapshots: dict, forecasts: dict) -> None:
        self._optimizer = optimizer
        self._snapshots = snapshots
        self._forecasts = forecasts

    def schedule_ready_tasks(self, dag: WorkflowDAG) -> list[dict]:
        """
        For each currently-ready task in the dag, produce an OptimizationDecision.
        Returns list of {task_id, decision} dicts.
        """
        from econode.models import Job, JobSpec

        results = []
        for task in dag.ready_tasks():
            slack = dag.task_slack(task.id)
            trigger = "deadline_pressure" if slack <= 0 else "dag_scheduled"

            # Wrap task as a Job so existing optimizer works unchanged
            spec = JobSpec(
                name=f"{dag.name}/{task.name}",
                gpu_count=task.gpu_count,
                duration_hours=task.duration_hours,
                deadline_hours=max(task.duration_hours + 0.1, slack),
                budget_usd=dag.budget_usd / max(1, dag.node_count),
                cost_weight=task.cost_weight,
                carbon_weight=task.carbon_weight,
            )
            job = Job(spec=spec)
            job.started_at = datetime.now(timezone.utc)

            try:
                decision = self._optimizer.evaluate(
                    job, self._forecasts, self._snapshots, trigger=trigger
                )
                task.assigned_region_id = decision.best_region_id
                results.append({"task_id": task.id, "decision": decision})
                log.info(
                    "DAG %s task %s → %s (slack=%.1fh, savings=%.1f%%)",
                    dag.name, task.name, decision.best_region_id,
                    slack, decision.savings_vs_baseline_pct,
                )
            except Exception as exc:
                log.error("DAG scheduling failed for task %s: %s", task.id, exc)

        return results
