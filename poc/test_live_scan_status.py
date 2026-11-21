"""Verify the live LMS 9.2 plugin withholds search during a rescan."""
import time

from poc.test_live_plugin_api import rpc


def main():
    assert rpc('serverstatus', '0', '10')['result']['version'] == '9.2.0'
    rpc('rescan')
    saw_updating = False
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = rpc('phoneticsearch', 'status', '?')['result']
        if status['state'] == 'updating':
            saw_updating = True
            result = rpc('phoneticsearch', '0', '20',
                         'query:alfa will', 'type:artist')['result']
            assert result.get('error') == 'index_not_ready', result
        if saw_updating and status['state'] == 'ready':
            result = rpc('phoneticsearch', '0', '20',
                         'query:alfa will', 'type:artist')['result']
            assert result['results_loop'][0]['name'] == 'Alphaville', result
            print('scan_status=ok updating_blocks_search=1 restored=ready')
            return
        time.sleep(.2)
    raise TimeoutError(f'No updating->ready cycle; saw_updating={saw_updating}')


if __name__ == '__main__':
    main()
