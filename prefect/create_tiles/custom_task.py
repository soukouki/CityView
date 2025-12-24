from prefect import Task
from prefect.context import FlowRunContext
from functools import wraps
from typing import Any, Callable, Optional

class PriorityTask(Task):
    """優先度とタスクタイプをサポートするカスタムTask"""
    
    def __init__(
        self,
        fn: Callable = None,
        priority: int = 0,
        task_type: str = "default",
        **kwargs
    ):
        super().__init__(fn=fn, **kwargs)
        self._priority = priority
        self._task_type = task_type
    
    def with_options(
        self,
        *,
        priority: int = None,
        task_type: str = None,
        name: str = None,
        description: str = None,
        tags: list = None,
        cache_key_fn: Callable = None,
        cache_expiration: Any = None,
        retries: int = None,
        retry_delay_seconds: Any = None,
        retry_jitter_factor: float = None,
        persist_result: bool = None,
        result_storage: Any = None,
        result_serializer: Any = None,
        timeout_seconds: float = None,
        log_prints: bool = None,
        refresh_cache: bool = None,
        on_completion: list = None,
        on_failure: list = None,
        **kwargs,
    ):
        # 新しいPriorityTaskを作成
        new_task = PriorityTask(
            fn=self.fn,
            priority=priority if priority is not None else self._priority,
            task_type=task_type if task_type is not None else self._task_type,
            name=name if name is not None else self.name,
            description=description if description is not None else self.description,
            tags=tags if tags is not None else self.tags,
            cache_key_fn=cache_key_fn if cache_key_fn is not None else self.cache_key_fn,
            cache_expiration=cache_expiration if cache_expiration is not None else self.cache_expiration,
            retries=retries if retries is not None else self.retries,
            retry_delay_seconds=retry_delay_seconds if retry_delay_seconds is not None else self.retry_delay_seconds,
            retry_jitter_factor=retry_jitter_factor if retry_jitter_factor is not None else self.retry_jitter_factor,
            persist_result=persist_result if persist_result is not None else self.persist_result,
            result_storage=result_storage if result_storage is not None else self.result_storage,
            result_serializer=result_serializer if result_serializer is not None else self.result_serializer,
            timeout_seconds=timeout_seconds if timeout_seconds is not None else self.timeout_seconds,
            log_prints=log_prints if log_prints is not None else self.log_prints,
            refresh_cache=refresh_cache if refresh_cache is not None else self.refresh_cache,
            on_completion=on_completion if on_completion is not None else self.on_completion,
            on_failure=on_failure if on_failure is not None else self.on_failure,
        )
        return new_task
    
    def submit(self, *args, wait_for=None, return_state=False, **kwargs):
        # 先にTaskRunnerに優先度を登録（submit前に登録が必要）
        ctx = FlowRunContext.get()
        if ctx and hasattr(ctx.task_runner, 'pre_submit_register'):
            ctx.task_runner.pre_submit_register(
                priority=self._priority,
                task_type=self._task_type,
            )
        
        future = super().submit(*args, wait_for=wait_for, return_state=return_state, **kwargs)
        return future


def priority_task(
    fn: Callable = None,
    *,
    priority: int = 0,
    task_type: str = "default",
    **task_kwargs
):
    """@taskの代わりに使用するデコレータ"""
    def decorator(fn: Callable) -> PriorityTask:
        return PriorityTask(
            fn=fn,
            priority=priority,
            task_type=task_type,
            **task_kwargs
        )
    
    if fn is not None:
        return decorator(fn)
    return decorator
