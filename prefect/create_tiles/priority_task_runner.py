from typing import Any, Callable, Coroutine, Dict, List, Optional
from uuid import UUID
import asyncio
import heapq
from dataclasses import dataclass, field
from prefect.task_runners import BaseTaskRunner, TaskConcurrencyType
from prefect.states import State
from prefect import Task
from prefect.context import FlowRunContext

@dataclass(order=True)
class PrioritizedTask:
    """優先度付きタスク"""
    priority: int
    sequence: int
    key: UUID = field(compare=False)
    call: Callable[[], Coroutine[Any, Any, State]] = field(compare=False)
    task_type: str = field(compare=False)


class PriorityTaskRunner(BaseTaskRunner):
    """優先度とタスクタイプ別同時実行制限をサポートするTaskRunner"""
    
    def __init__(
        self,
        max_workers: int = 14,
        concurrency_limits: Optional[Dict[str, int]] = None,
    ):
        super().__init__()
        self.max_workers = max_workers
        self.concurrency_limits = concurrency_limits or {}
        
        self._task_queue: List[PrioritizedTask] = []
        self._queue_sequence = 0
        self._running_count_by_type: Dict[str, int] = {}
        self._total_running: int = 0
        self._results: Dict[UUID, State] = {}
        self._pending_futures: Dict[UUID, asyncio.Future] = {}
        
        self._lock: Optional[asyncio.Lock] = None
        self._schedule_event: Optional[asyncio.Event] = None
        
        self._pending_priority: int = 0
        self._pending_task_type: str = "default"
        
        self._scheduler_task: Optional[asyncio.Task] = None
        self._started: bool = False
    
    @property
    def concurrency_type(self) -> TaskConcurrencyType:
        return TaskConcurrencyType.CONCURRENT
    
    def duplicate(self):
        """新しいインスタンスを作成"""
        return PriorityTaskRunner(
            max_workers=self.max_workers,
            concurrency_limits=self.concurrency_limits.copy(),
        )
    
    def pre_submit_register(self, priority: int, task_type: str):
        """submit前に優先度を登録"""
        self._pending_priority = priority
        self._pending_task_type = task_type
    
    def _ensure_initialized(self):
        """遅延初期化：asyncioオブジェクトを作成"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._schedule_event is None:
            self._schedule_event = asyncio.Event()
    
    async def _start(self, exit_stack=None):
        """TaskRunnerを開始（BaseTaskRunnerから呼ばれる）"""
        if self._started:
            return
        
        self._started = True
        
        # asyncioオブジェクトを初期化
        self._ensure_initialized()
        
        # 内部状態を初期化
        self._task_queue = []
        self._queue_sequence = 0
        self._running_count_by_type = {t: 0 for t in self.concurrency_limits}
        self._running_count_by_type["default"] = 0
        self._total_running = 0
        self._results = {}
        self._pending_futures = {}
        
        # スケジューラを開始
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        print(f"[PriorityTaskRunner] Started with max_workers={self.max_workers}, limits={self.concurrency_limits}")
    
    async def _stop(self, exit_stack=None):
        """TaskRunnerを停止（BaseTaskRunnerから呼ばれる）"""
        print("[PriorityTaskRunner] Shutting down...")
        self._started = False
        
        if self._schedule_event:
            self._schedule_event.set()
        
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        print("[PriorityTaskRunner] Shutdown complete")
    
    async def submit(
        self,
        key: UUID,
        call: Callable[[], Coroutine[Any, Any, State]],
    ) -> None:
        """タスクをキューに追加"""
        self._ensure_initialized()
        
        if not self._started:
            await self._start()
        
        # callからtask_runを取得し、タグから優先度を読み取る
        priority = 0
        task_type = 'default'
        
        # callがpartialの場合、keywordsからtask_runを取得
        if hasattr(call, 'keywords'):
            task_run = call.keywords.get('task_run')
            if task_run and hasattr(task_run, 'tags'):
                for tag in (task_run.tags or []):
                    if tag.startswith('__priority:'):
                        try:
                            priority = int(tag.split(':', 1)[1])
                        except (ValueError, IndexError):
                            pass
                    elif tag.startswith('__task_type:'):
                        try:
                            task_type = tag.split(':', 1)[1]
                        except IndexError:
                            pass
        
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_futures[key] = future
        
        async with self._lock:
            self._queue_sequence += 1
            task = PrioritizedTask(
                priority=-priority,
                sequence=self._queue_sequence,
                key=key,
                call=call,
                task_type=task_type,
            )
            heapq.heappush(self._task_queue, task)
            print(f"[PriorityTaskRunner] Submitted task {key} priority={priority}, type={task_type}, queue={len(self._task_queue)}")
        
        self._schedule_event.set()
    
    async def wait(self, key: UUID, timeout: Optional[float] = None) -> State:
        """タスクの完了を待つ"""
        if key in self._results:
            return self._results.pop(key)
        
        future = self._pending_futures.get(key)
        if future is None:
            raise KeyError(f"Unknown task key: {key}")
        
        try:
            if timeout is not None:
                result = await asyncio.wait_for(future, timeout=timeout)
            else:
                result = await future
            return result
        finally:
            self._pending_futures.pop(key, None)
    
    def _can_run_task(self, task_type: str) -> bool:
        """タスク実行可能かチェック"""
        if self._total_running >= self.max_workers:
            return False
        
        if task_type in self.concurrency_limits:
            limit = self.concurrency_limits[task_type]
            current = self._running_count_by_type.get(task_type, 0)
            if current >= limit:
                return False
        
        return True
    
    async def _scheduler_loop(self):
        """スケジューラメインループ"""
        print("[PriorityTaskRunner] Scheduler started")
        
        while self._started:
            try:
                try:
                    await asyncio.wait_for(self._schedule_event.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass
                
                self._schedule_event.clear()
                await self._schedule_tasks()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[PriorityTaskRunner] Scheduler error: {e}")
                import traceback
                traceback.print_exc()
        
        print("[PriorityTaskRunner] Scheduler ended")
    
    async def _schedule_tasks(self):
        """実行可能なタスクをスケジュール"""
        async with self._lock:
            tasks_to_run: List[PrioritizedTask] = []
            remaining: List[PrioritizedTask] = []
            
            while self._task_queue:
                task = heapq.heappop(self._task_queue)
                
                if self._can_run_task(task.task_type):
                    tasks_to_run.append(task)
                    self._running_count_by_type[task.task_type] = \
                        self._running_count_by_type.get(task.task_type, 0) + 1
                    self._total_running += 1
                    print(f"[PriorityTaskRunner] Scheduling {task.key} type={task.task_type} total={self._total_running}")
                else:
                    remaining.append(task)
            
            for task in remaining:
                heapq.heappush(self._task_queue, task)
        
        for task in tasks_to_run:
            asyncio.create_task(self._run_task(task))
    
    async def _run_task(self, task: PrioritizedTask):
        """タスク実行"""
        try:
            print(f"[PriorityTaskRunner] Running {task.key}")
            result = await task.call()
            print(f"[PriorityTaskRunner] Completed {task.key}")
            
            self._results[task.key] = result
            
            future = self._pending_futures.get(task.key)
            if future and not future.done():
                future.set_result(result)
                
        except Exception as e:
            print(f"[PriorityTaskRunner] Failed {task.key}: {e}")
            import traceback
            traceback.print_exc()
            
            future = self._pending_futures.get(task.key)
            if future and not future.done():
                future.set_exception(e)
        finally:
            async with self._lock:
                self._running_count_by_type[task.task_type] -= 1
                self._total_running -= 1
                print(f"[PriorityTaskRunner] Finished {task.key} total={self._total_running} queue={len(self._task_queue)}")
            
            self._schedule_event.set()
