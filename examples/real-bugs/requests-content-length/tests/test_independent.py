from requests.utils import super_len

def test_utf8_content_lengths():
    for text in ['café','€','你好','😀']:
        assert super_len(text)==len(text.encode('utf-8'))
    assert super_len('')==0
