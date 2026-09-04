import importlib.util
import os
import socket
import socketserver
import threading
import uuid
from pathlib import Path


def load_bridge():
    path = Path(__file__).parents[1] / "scripts" / "rpc_bridge.py"
    spec = importlib.util.spec_from_file_location("microduck_rpc_bridge", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tcp_bridge_accepts_pathlib_unix_socket():
    bridge = load_bridge()
    socket_path = Path(f"/tmp/md-bridge-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock")

    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.sendall(self.request.recv(4))

    unix_server = socketserver.UnixStreamServer(str(socket_path), Echo)
    unix_thread = threading.Thread(target=unix_server.serve_forever)
    unix_thread.start()

    handler = type(
        "TestTcpToUnixHandler",
        (bridge.TcpToUnixHandler,),
        {"unix_socket": socket_path},
    )
    tcp_server = bridge.ThreadingTcpServer(("127.0.0.1", 0), handler)
    tcp_thread = threading.Thread(target=tcp_server.serve_forever)
    tcp_thread.start()

    try:
        with socket.create_connection(tcp_server.server_address) as client:
            client.sendall(b"ping")
            assert client.recv(4) == b"ping"
    finally:
        tcp_server.shutdown()
        tcp_server.server_close()
        unix_server.shutdown()
        unix_server.server_close()
        tcp_thread.join()
        unix_thread.join()
        socket_path.unlink(missing_ok=True)
