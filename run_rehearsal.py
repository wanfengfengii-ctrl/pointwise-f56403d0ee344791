import argparse
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from dispatch.http import serve_duty
from lamp.http import serve_lamp


SHOW = "qinghe"


def with_readiness(handler):
    class Handler(handler):
        def do_GET(self):
            if self.path != "/health":
                return super().do_GET()
            payload = b"{\"ready\":true}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Start the rehearsal HTTP services")
    parser.add_argument("--host", choices=("127.0.0.1",), required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    with ExitStack() as stack:
        if args.state_dir is None:
            directory = Path(stack.enter_context(TemporaryDirectory(prefix="qinghe-api-")))
        else:
            directory = args.state_dir
            directory.mkdir(parents=True, exist_ok=True)
        lamps = {name: stack.enter_context(closing(serve_lamp(directory / (name + ".sqlite3"),
                                                             SHOW, name, args.port)))
                 for name in ("alpha", "beta")}
        ports = {name: server.server_port for name, server in lamps.items()}
        duty = stack.enter_context(closing(serve_duty(directory / "duty.sqlite3", SHOW, ports, args.port)))
        duty.RequestHandlerClass = with_readiness(duty.RequestHandlerClass)
        for server in lamps.values():
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
            thread.start()
            stack.callback(thread.join)
            stack.callback(server.shutdown)
        try:
            duty.serve_forever()
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
