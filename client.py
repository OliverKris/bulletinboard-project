# client.py
import socket
import os

HOST = "127.0.0.1"
PORT = int(os.environ.get("BBS_PORT", "6500"))

class ClientConn:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = b""

    def read_line(self) -> str | None:
        """
        Read exactly one newline-terminated line, preserving any extra bytes.
        Returns line including '\n', or None if connection closed cleanly.
        """
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self.buf += chunk

        line, self.buf = self.buf.split(b"\n", 1)
        return (line + b"\n").decode("utf-8")

def recv_count_framed(conn: ClientConn, first_line: str, expected_prefix: str) -> str | None:
    """
    Handles:
        OK LIST <n>\n + n lines
        OK HELP <n>\n + n lines
    """
    if not first_line.startswith(expected_prefix):
        return first_line

    parts = first_line.strip().split()
    if len(parts) != 3:
        return first_line

    try:
        n = int(parts[2])
    except ValueError:
        return first_line

    lines = [first_line]
    for _ in range(n):
        nxt = conn.read_line()
        if nxt is None:
            return None
        lines.append(nxt)

    return "".join(lines)

def recv_response(conn: ClientConn, sent_cmd: str) -> str | None:
    """
    Response:
        - LIST: OK LIST <count>\n then <count> lines
        - HELP: OK HELP <count>\n then <count> lines
        - Most other commands: single line
    """
    first = conn.read_line()
    if first is None:
        return None

    cmd = sent_cmd.strip().split(" ", 1)[0].upper()

    if cmd == "LIST":
        return recv_count_framed(conn, first, "OK LIST ")

    if cmd == "HELP":
        return recv_count_framed(conn, first, "OK HELP ")

    return first

def main():
    print(f"Connecting to server at {HOST}:{PORT}...")
    try:
        sock = socket.create_connection((HOST, PORT))
    except ConnectionRefusedError:
        print("Could not connect - is the server running?")
        return

    conn = ClientConn(sock)

    print("Connected. Type commands or QUIT to exit.")
    print("Try: HELP")
    print("Try: LOGIN oliver pw1")
    print()

    try:
        while True:
            try:
                user_input = input("> ")
            except EOFError:
                break

            if not user_input.strip():
                continue

            try:
                sock.sendall((user_input.rstrip("\n") + "\n").encode("utf-8"))
            except ConnectionError:
                print("Connection lost while sending.")
                break

            response = recv_response(conn, user_input)
            if response is None:
                print("Server closed the connection.")
                break

            print(response, end="")

            if user_input.strip().upper() == "QUIT":
                break

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        print("Closing connection.")
        try:
            sock.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()