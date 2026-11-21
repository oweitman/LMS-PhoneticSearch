"""Exercise settings save against the isolated LMS 9.2 plugin, then restore 5 s."""
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from poc.test_live_plugin_api import rpc


URL = 'http://127.0.0.1:9002/settings/plugins/PhoneticSearch/settings/basic.html'


class Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = URL
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('action'):
            self.action = urljoin(URL, attrs['action'])
        if tag == 'input' and attrs.get('name'):
            self.fields[attrs['name']] = attrs.get('value', '')


def page():
    with urlopen(URL, timeout=15) as response:
        body = response.read().decode('utf-8')
    form = Form()
    form.feed(body)
    return form, body


def save(value):
    form, _ = page()
    form.fields.update({'saveSettings': '1',
                        'pref_reconcile_interval_seconds': str(value)})
    request = Request(form.action, data=urlencode(form.fields).encode())
    with urlopen(request, timeout=15) as response:
        response.read()
    return rpc('phoneticsearch', 'status', '?')['result']['interval_seconds']


def main():
    try:
        changed = save(10)
        invalid = save(4)
    finally:
        restored = save(5)
    assert (changed, invalid, restored) == (10, 10, 5), (changed, invalid, restored)
    status = rpc('phoneticsearch', 'status', '?')['result']
    if 'last_reconcile_duration_ms' in status:
        _, body = page()
        assert 'phoneticsearch_reconcile_duration' in body
        expected = status.get('suggested_interval_seconds')
        assert ('phoneticsearch_interval_suggestion' in body) == (expected is not None)
    print('settings=ok changed=10 invalid_preserved=10 restored=5 '
          f'duration_ms={status.get("last_reconcile_duration_ms", "unavailable")} '
          f'suggestion={status.get("suggested_interval_seconds", "none")}')


if __name__ == '__main__':
    main()
