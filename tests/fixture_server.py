from session_desk.demo import demo_store
from session_desk.server import make_server

with demo_store() as store:
    server = make_server(store, port=8768)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
