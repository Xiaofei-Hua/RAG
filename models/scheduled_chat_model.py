"""Apply the local admission policy at each actual SDK invocation."""

import os
from contextlib import aclosing, closing, nullcontext

from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import BaseChatOpenAI

from models import local_model_queue
from models.local_rag_policy import bounded_local_rag


class ScheduledChatOpenAI(ChatOpenAI):
    def _queue_lease(self, kwargs, asynchronous=False):
        enabled = os.getenv("LOCAL_LLM_SCHEDULER", "off").lower() == "fair"
        if not enabled or not bounded_local_rag(self):
            return nullcontext()
        budget = (kwargs.get("extra_body") or {}).get("max_tokens")
        budget = budget or kwargs.get("max_tokens") or self.max_tokens
        short = isinstance(budget, int) and 0 < budget <= 256
        queue = local_model_queue._model_queue
        return queue.alease(short) if asynchronous else queue.lease(short)

    def _generate(self, *args, **kwargs):
        with self._queue_lease(kwargs):
            return super()._generate(*args, **kwargs)

    async def _agenerate(self, *args, **kwargs):
        async with self._queue_lease(kwargs, asynchronous=True):
            return await super()._agenerate(*args, **kwargs)

    def _stream(self, *args, **kwargs):
        with self._queue_lease(kwargs), closing(super()._stream(*args, **kwargs)) as stream:
            yield from stream

    async def _astream(self, *args, **kwargs):
        # 直接持有实际SDK流，关闭时先取消推理再归还模型槽。
        method = (
            BaseChatOpenAI._astream_responses
            if self._use_responses_api({**kwargs, **self.model_kwargs})
            else BaseChatOpenAI._astream
        )
        async with (
            self._queue_lease(kwargs, asynchronous=True),
            aclosing(method(self, *args, **kwargs)) as stream,
        ):
            async for chunk in stream:
                yield chunk
