# tests/test_sse.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from a2a_cli.transport.sse import JSONRPCSSEClient
from a2a_json_rpc.json_rpc_errors import JSONRPCError

class FakeContext:
    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def aiter_lines(self):
        for line in self.lines:
            yield line

@pytest.mark.asyncio
async def test_sse_call_and_notify():
    # Create the client
    client = JSONRPCSSEClient("http://test", "http://test/stream")
    
    # Create a more comprehensive fake response
    class FakeResp:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code
            self.content = True
            self.headers = {"content-type": "application/json"}
        
        def raise_for_status(self):
            pass
        
        # Make json() asynchronous
        async def json(self):
            return self._data
        
        async def aclose(self):
            pass
        
        # Add aiter_lines method for streaming
        async def aiter_lines(self):
            yield "data: " + json.dumps(self._data)
    
    # Replace both send and post methods with mocks
    client._client.send = AsyncMock(return_value=FakeResp(
        {"jsonrpc": "2.0", "result": 42, "id": None}
    ))
    
    client._client.post = AsyncMock(return_value=FakeResp(
        {"jsonrpc": "2.0", "result": 42, "id": None}
    ))
    
    # Test successful call
    result = await client.call("foo", {"a": 1})
    assert result == 42
    
    # Test error
    error_resp = FakeResp(
        {"jsonrpc": "2.0", "error": {"code": -32602, "message": "Bad params"}, "id": None}
    )
    client._client.send = AsyncMock(return_value=error_resp)
    
    with pytest.raises(JSONRPCError):
        await client.call("foo", {})
    
    # Test notify
    client._client.post = AsyncMock(return_value=FakeResp({}))
    await client.notify("foo", {"x": 2})
    assert client._client.post.called

@pytest.mark.asyncio
async def test_sse_stream():
    data1 = json.dumps({"jsonrpc": "2.0", "result": {"val": 1}})
    data2 = json.dumps({"jsonrpc": "2.0", "result": {"val": 2}})
    
    class EnhancedFakeContext:
        def __init__(self, lines):
            self.lines = lines

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def aiter_lines(self):
            for line in self.lines:
                yield line
                
        def raise_for_status(self):
            pass
    
    fake_context = EnhancedFakeContext([
        "\n",
        ": comment",
        f"data: {data1}\n",
        f"data:{data2}\n",
    ])
    
    client = JSONRPCSSEClient("http://test", "http://test/stream")
    client._client.stream = lambda *args, **kwargs: fake_context

    outputs = []
    async for msg in client.stream():
        outputs.append(msg)
        if len(outputs) == 2:
            break
    assert outputs[0]["result"]["val"] == 1
    assert outputs[1]["result"]["val"] == 2