from gi.repository import Gio, GLib
import secrets

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
destination = 'org.freedesktop.portal.Desktop'
desktop = '/org/freedesktop/portal/desktop'
interface = 'org.freedesktop.portal.RemoteDesktop'
sender = bus.get_unique_name()[1:].replace('.', '_')

def request(method, signature, args, options, api=interface):
    token = 'demo' + secrets.token_hex(8)
    path = f'{desktop}/request/{sender}/{token}'
    loop = GLib.MainLoop()
    result = []
    def response(*event):
        result.extend(event[5].unpack())
        loop.quit()
    subscription = bus.signal_subscribe(destination, 'org.freedesktop.portal.Request', 'Response', path, None, Gio.DBusSignalFlags.NONE, response)
    options['handle_token'] = GLib.Variant('s', token)
    try:
        bus.call_sync(destination, desktop, api, method, GLib.Variant(signature, (*args, options)), None, Gio.DBusCallFlags.NONE, 5000, None)
        print(method + ' request sent', flush=True)
        loop.run()
        return result
    finally:
        bus.signal_unsubscribe(subscription)

def main():
    code, result = request('CreateSession', '(a{sv})', (), {'session_handle_token': GLib.Variant('s', 'demo' + secrets.token_hex(8))})
    if code:
        raise SystemExit(f'CreateSession response {code}')
    session = result['session_handle']
    try:
        code, _ = request('SelectDevices', '(oa{sv})', (session,), {'types': GLib.Variant('u', 3)})
        if code:
            raise SystemExit(f'SelectDevices response {code}')
        code, _ = request('Start', '(osa{sv})', (session, ''), {})
        print(f'Start response {code}', flush=True)
    finally:
        bus.call_sync(destination, session, 'org.freedesktop.portal.Session', 'Close', None, None, Gio.DBusCallFlags.NONE, 5000, None)

if __name__ == '__main__':
    main()
