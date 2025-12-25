# server.py
import socket
import select
import os

from protocol import process_line

HOST = "0.0.0.0"
PORT = int(os.environ.get("BBS_PORT", "6500"))
MAX_BUFFER_BYTES = 64 * 1024

class ClientState:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.buffer = ""
        self.username = None
        self.role = None
        self.authenticated = False

    def fileno(self):
        return self.sock.fileno()

    def __repr__(self):
        return f"<ClientState {self.addr} {self.username}>"

clients = {} # socket -> ClientState

def create_listening_socket(host, port):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, port))
    server_sock.listen()
    print(f"Server listening on {host}:{port}")
    return server_sock

def close_client(sock):
    client = clients.get(sock)
    try:
        sock.close()
    except Exception:
        pass
    if client is not None:
        del clients[sock]

def handle_client_socket(sock):
    client = clients.get(sock)
    if client is None:
        # Unknown socket; close defensively
        try:
            sock.close()
        except Exception:
            pass
        return

    try:
        data = sock.recv(4096)
    except ConnectionError:
        data = b""

    if not data:
        print(f"Client {client.addr} disconnected")
        close_client(sock)
        return

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        print(f"Bad data from {client.addr}, closing connection")
        close_client(sock)
        return

    client.buffer += text

    # Max buffer guard: if client sends a really long message
    # cap memory usage and drop
    if len(client.buffer.encode("utf-8", errors="ignore")) > MAX_BUFFER_BYTES:
        try:
            client.sock.sendall(b"ERR Line too long\n")
        except Exception:
            pass
        close_client(sock)
        return

    while "\n" in client.buffer:
        raw_line, client.buffer = client.buffer.split("\n", 1)
        # Only remove CR. Do NOT strip spaces.
        line = raw_line.rstrip("\r")

        if line == "":
            continue

        print(f"Received from {client.addr}: {line}")

        response, should_close = process_line(client, line)

        if response:
            try:
                client.sock.sendall(response.encode("utf-8"))
            except ConnectionError:
                print(f"Error sending to {client.addr}, closing connection")
                close_client(sock)
                return

        if should_close:
            print(f"Closing connection for {client.addr} (protocol requested close)")
            close_client(sock)
            return

def main():
    server_sock = create_listening_socket(HOST, PORT)

    try:
        while True:
            read_list = [server_sock] + [c.sock for c in clients.values()]

            try:
                readable, _, _ = select.select(read_list, [], [])
            except OSError:
                # Defensive: if a fd becomes invalid, rebuild loop
                continue

            for sock in readable:
                if sock is server_sock:
                    new_sock, addr = server_sock.accept()
                    print(f"New connection from {addr}")
                    clients[new_sock] = ClientState(new_sock, addr)
                else:
                    handle_client_socket(sock)

    except KeyboardInterrupt:
        print("\nShutting down server.")
    finally:
        for s in list(clients.keys()):
            close_client(s)
        server_sock.close()

if __name__ == "__main__":
    main()
