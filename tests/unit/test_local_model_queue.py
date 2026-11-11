import asyncio
import threading

import pytest


def test_short_burst_cannot_starve_generation():
    from models.local_model_queue import LocalModelQueue

    queue = LocalModelQueue(clock=lambda: 0)
    woke = []
    active = queue.submit(False, lambda: None)
    generation = queue.submit(False, lambda: woke.append("generation"))
    controls = [queue.submit(True, lambda i=i: woke.append(i)) for i in range(3)]
    queue.release(active)
    assert woke == [0]
    queue.release(controls[0])
    assert woke == [0, 1]
    queue.release(controls[1])
    assert woke == [0, 1, "generation"]
    queue.release(generation)
    queue.release(controls[2])
    assert queue.pending == 0 and queue.active_count == 0


def test_queue_limit_is_a_typed_busy_terminal():
    from models.local_model_queue import LocalModelQueue, ModelBusyError

    queue = LocalModelQueue(max_waiting=1)
    active = queue.submit(False, lambda: None)
    queued = queue.submit(False, lambda: None)
    with pytest.raises(ModelBusyError, match="queue_full"):
        queue.submit(True, lambda: None)
    assert queue.pending == 1
    queue.release(active)
    queue.release(queued)
    assert queue.active_count == 0


def test_aged_generation_precedes_a_new_short_call():
    from models.local_model_queue import LocalModelQueue

    now = [0.0]
    queue = LocalModelQueue(clock=lambda: now[0])
    woke = []
    active = queue.submit(False, lambda: None)
    generation = queue.submit(False, lambda: woke.append("generation"))
    now[0] = 3.0
    short = queue.submit(True, lambda: woke.append("short"))
    queue.release(active)
    assert woke == ["generation"]
    queue.release(generation)
    queue.release(short)


@pytest.mark.parametrize("grant_before_cancel", [False, True])
def test_async_cancel_removes_waiter_and_releases_a_racing_grant(monkeypatch, grant_before_cancel):
    from models.local_model_queue import LocalModelQueue

    async def run():
        queue = LocalModelQueue()
        active = queue.submit(False, lambda: None)
        waiting = asyncio.Event()
        submit = queue.submit

        def notify(*args):
            ticket = submit(*args)
            waiting.set()
            return ticket

        monkeypatch.setattr(queue, "submit", notify)

        async def request():
            async with queue.alease():
                pytest.fail("cancelled request must not execute")

        task = asyncio.create_task(request())
        await asyncio.wait_for(waiting.wait(), 1)
        if grant_before_cancel:
            queue.release(active)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        if not grant_before_cancel:
            queue.release(active)
        assert queue.active_count == queue.pending == 0
        async with queue.alease():
            assert queue.active_count == 1
        assert queue.active_count == 0

    asyncio.run(run())


def test_queue_timeout_does_not_enter_the_model():
    from models.local_model_queue import LocalModelQueue, ModelBusyError

    async def run():
        queue = LocalModelQueue(wait_timeout=0)
        active = queue.submit(False, lambda: None)
        with pytest.raises(ModelBusyError, match="queue_timeout"):
            async with queue.alease():
                pytest.fail("timed out request entered")
        assert queue.pending == 0
        queue.release(active)
        assert queue.active_count == 0

    asyncio.run(run())


def test_sync_and_async_clients_share_one_slot(monkeypatch):
    from models.local_model_queue import LocalModelQueue

    async def run():
        queue = LocalModelQueue()
        running, release, waiting = threading.Event(), threading.Event(), asyncio.Event()

        def sync_request():
            with queue.lease():
                running.set()
                assert release.wait(2)

        thread = threading.Thread(target=sync_request)
        thread.start()
        assert await asyncio.to_thread(running.wait, 1)
        submit = queue.submit

        def notify(*args):
            ticket = submit(*args)
            waiting.set()
            return ticket

        monkeypatch.setattr(queue, "submit", notify)
        entered = []

        async def async_request():
            async with queue.alease():
                entered.append(True)

        task = asyncio.create_task(async_request())
        await asyncio.wait_for(waiting.wait(), 1)
        assert not entered and queue.active_count == 1
        release.set()
        await asyncio.wait_for(task, 1)
        await asyncio.to_thread(thread.join, 1)
        assert entered == [True] and not thread.is_alive()
        assert queue.active_count == queue.pending == 0

    asyncio.run(run())


@pytest.mark.parametrize("entry", ["sync", "async"])
def test_classifier_busy_is_not_retried_or_converted_to_zero(monkeypatch, entry):
    from core.intent.classifier import IntentClassifier
    from models.local_model_queue import ModelBusyError

    classifier = IntentClassifier(llm=None)
    calls = []

    class Busy:
        def invoke(self, *args, **kwargs):
            calls.append(True)
            raise ModelBusyError("queue_full")

        async def ainvoke(self, *args, **kwargs):
            return self.invoke()

    monkeypatch.setattr(IntentClassifier, "chain", property(lambda self: Busy()))
    with pytest.raises(ModelBusyError):
        if entry == "sync":
            classifier.classify("Compare the documented capacities")
        else:
            asyncio.run(classifier.aclassify("Compare the documented capacities"))
    assert len(calls) == 1


def test_public_stream_close_releases_transport_before_slot(monkeypatch, bounded_local_model):
    import httpx

    from models import local_model_queue
    from models.scheduled_chat_model import ScheduledChatOpenAI

    async def run():
        queue = local_model_queue.LocalModelQueue()
        monkeypatch.setattr(local_model_queue, "_model_queue", queue)
        monkeypatch.setenv("LOCAL_LLM_SCHEDULER", "fair")

        class Body(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                yield b'data: {"choices":[{"index":0,"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
                await asyncio.Event().wait()

            async def aclose(self):
                assert queue.active_count == 1
                self.closed = True

        body = Body()
        closing, finish_close = asyncio.Event(), asyncio.Event()
        original_close = body.aclose

        async def slow_close():
            closing.set()
            await finish_close.wait()
            await original_close()

        body.aclose = slow_close
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, stream=body, headers={"content-type": "text/event-stream"}
                )
            )
        ) as http:
            model = ScheduledChatOpenAI(
                model="qwen3.5:9b",
                api_key="ollama",
                base_url="http://127.0.0.1:11434/v1",
                max_retries=0,
                http_async_client=http,
            )
            stream = model.astream("hello")
            chunk = await anext(stream)
            assert chunk.content == "hello" and queue.active_count == 1
            closing_task = asyncio.create_task(stream.aclose())
            await asyncio.wait_for(closing.wait(), 1)
            assert not closing_task.done()
            finish_close.set()
            await closing_task
            assert body.closed
            assert queue.active_count == 0

    asyncio.run(run())


@pytest.mark.parametrize("entry", ["sync", "async", "condense"])
def test_query_transform_busy_propagates_without_fallback(monkeypatch, entry):
    from unittest.mock import AsyncMock, Mock

    from langchain_core.messages import HumanMessage

    from core.retrieval import query_transform
    from models.local_model_queue import ModelBusyError

    monkeypatch.setattr(query_transform, "_cache_get", lambda *args: None)
    llm = Mock()
    llm.invoke.side_effect = ModelBusyError("queue_full")
    llm.ainvoke = AsyncMock(side_effect=ModelBusyError("queue_full"))
    monkeypatch.setattr("models.llm_models.create_custom_llm", lambda **kw: llm)
    with pytest.raises(ModelBusyError):
        if entry == "async":
            asyncio.run(query_transform._allm_invoke("独立测试"))
        elif entry == "condense":
            query_transform.condense_query("那它需要多少天？", [HumanMessage(content="校准")])
        else:
            query_transform._llm_invoke("独立测试")
