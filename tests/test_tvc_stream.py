import asyncio
import json

from collector import tvc


def _f(obj):
    s = json.dumps(obj)
    return f"~m~{len(s)}~m~{s}"


class FakeWS:
    def __init__(self, msgs):
        self.msgs, self.sent = list(msgs), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, x):
        self.sent.append(x)

    async def recv(self):
        if not self.msgs:
            raise ConnectionError("closed")
        return self.msgs.pop(0)


def _upd(m, t, c):
    return _f({"m": m, "p": ["cs", {"sds_1": {"s": [{"i": 0, "v": [t, 1, 2, 0.5, c, 3]}]}}]})


def test_stream_minutes_yields_changes_only_and_answers_heartbeat():
    ws = FakeWS([_upd("timescale_update", 100, 1.5), "~m~4~m~~h~1", _upd("du", 100, 1.5), _upd("du", 100, 1.7), _upd("du", 160, 1.8)])

    async def run():
        got = []
        try:
            async for r in tvc.stream_minutes(connect=lambda *a, **k: ws):
                got.append((r[0], r[4]))
        except ConnectionError:
            pass
        return got

    assert asyncio.run(run()) == [(100, 1.5), (100, 1.7), (160, 1.8)]
    assert any("~h~1" in x for x in ws.sent)
