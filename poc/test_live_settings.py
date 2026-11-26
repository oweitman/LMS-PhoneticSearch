"""Check the event-driven settings page on an isolated LMS instance."""
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import urlopen

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


def main():
    status = rpc('phoneticsearch', 'status', '?')['result']
    assert 'interval_seconds' not in status
    assert 'suggested_interval_seconds' not in status
    _, body = page()
    assert 'pref_reconcile_interval_seconds' not in body
    assert 'phoneticsearch_interval_suggestion' not in body
    if 'last_reconcile_duration_ms' in status:
        assert 'phoneticsearch_reconcile_duration' in body
    print('settings=ok update_mode=scan_events '
          f'duration_ms={status.get("last_reconcile_duration_ms", "unavailable")}')


if __name__ == '__main__':
    main()
