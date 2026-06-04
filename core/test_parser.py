from core.assistant import _parse_ollama_response


class FakeResponse:
    def __init__(self, lines, text=''):
        self._lines = lines
        self.text = text

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            yield line

    def json(self):
        raise ValueError('no json')


resp = FakeResponse([
    b'data: {"message":{"content":"Ho"}}\n',
    b'data: {"message":{"content":"la"}}\n',
    b'data: {"done": true}\n',
])
print('stream result:', _parse_ollama_response(resp))


class FullResp:
    def __init__(self, obj):
        self._obj = obj
        self.text = str(obj)

    def json(self):
        return self._obj

    def iter_lines(self, decode_unicode=False):
        yield b''


full = FullResp({
    "message": {
        "role": "assistant",
        "content": "Hola, en que puedo ayudarte?",
        "thinking": "Thinking Process...",
    }
})
print('full json result:', _parse_ollama_response(full))

resp2 = FakeResponse([
    b'data: {"message":{"thinking":"processing"}}\n',
    b'data: {"message":{"content":"Respuesta real"}}\n',
], text='')
print('stream ignores thinking result:', _parse_ollama_response(resp2))
