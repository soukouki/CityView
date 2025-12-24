from prefect import Task
from prefect.context import FlowRunContext
from typing import Any, Callable


class PriorityTask(Task):
    """優先度とタスクタイプをサポートするカスタムTask"""
    
    def __init__(self, fn: Callable = None, priority: int = 0, task_type: str = "default", **kwargs):
        # タグに優先度情報を埋め込む
        tags = list(kwargs.pop('tags', None) or [])
        tags = [t for t in tags if not t.startswith('__priority:') and not t.startswith('__task_type:')]
        tags.append(f'__priority:{priority}')
        tags.append(f'__task_type:{task_type}')
        
        super().__init__(fn=fn, tags=tags, **kwargs)
        self._priority = priority
        self._task_type = task_type
    
    def with_options(self, *, priority: int = None, task_type: str = None, **kwargs):
        new_priority = priority if priority is not None else self._priority
        new_task_type = task_type if task_type is not None else self._task_type
        
        # タグに優先度情報を埋め込む
        existing_tags = list(kwargs.pop('tags', None) or self.tags or [])
        existing_tags = [t for t in existing_tags if not t.startswith('__priority:') and not t.startswith('__task_type:')]
        existing_tags.append(f'__priority:{new_priority}')
        existing_tags.append(f'__task_type:{new_task_type}')
        kwargs['tags'] = existing_tags
        
        result = super().with_options(**kwargs)
        result.__class__ = PriorityTask
        result._priority = new_priority
        result._task_type = new_task_type
        
        return result
    
    def submit(self, *args, wait_for=None, return_state=False, **kwargs):
        # タグに既に埋め込まれているので、追加の処理は不要
        return super().submit(*args, wait_for=wait_for, return_state=return_state, **kwargs)


def priority_task(fn: Callable = None, *, priority: int = 0, task_type: str = "default", **task_kwargs):
    """@taskの代わりに使用するデコレータ"""
    def decorator(fn: Callable) -> PriorityTask:
        return PriorityTask(fn=fn, priority=priority, task_type=task_type, **task_kwargs)
    
    if fn is not None:
        return decorator(fn)
    return decorator
