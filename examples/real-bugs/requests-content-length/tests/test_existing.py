import io
from requests.utils import super_len

def test_ascii_and_streams():
    assert super_len('abc') == 3
    assert super_len(b'abc') == 3
    stream=io.BytesIO(b'abcdef');stream.seek(2)
    assert super_len(stream)==4
