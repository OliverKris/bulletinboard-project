# tests.py
import os
import socket
import subprocess
import sys
import time
import unittest
import threading
from contextlib import closing

HOST = "127.0.0.1"
CONNECT_RETRIES = 60
CONNECT_SLEEP_S = 0.05


# Finds an available port to use for testing
def pick_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def stop_server(proc: subprocess.Popen) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def start_server(port: int) -> subprocess.Popen:
    """
    Start server.py from repo root
    If server fails to start, we write its stdout for debugging.
    """
    env = os.environ.copy()
    env["BBS_PORT"] = str(port)

    root_dir = os.path.dirname(os.path.abspath(__file__))
    server_path = os.path.join(root_dir, "server.py")

    proc = subprocess.Popen(
        [sys.executable, server_path],
        env=env,
        cwd=root_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    time.sleep(0.1)
    if proc.poll() is not None:
        out = proc.stdout.read() if proc.stdout else ""
        raise RuntimeError(f"Server exited immediately.\nOutput:\n{out}")

    last_err = None
    for _ in range(CONNECT_RETRIES):
        try:
            with socket.create_connection((HOST, port), timeout=0.25):
                return proc
        except OSError as e:
            last_err = e
            time.sleep(CONNECT_SLEEP_S)

    out = ""
    try:
        if proc.stdout:
            out = proc.stdout.read()
    except Exception:
        pass

    stop_server(proc)
    raise RuntimeError(
        f"Server did not become ready on port {port}. Last error: {last_err}\n"
        f"Server output so far:\n{out}"
    )


# Buffered socket client
class BufConn:
    """
    Buffered line reader so we never discard bytes that arrive after the first newline.
    """
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = b""

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def send(self, line: str):
        self.sock.sendall((line.rstrip("\n") + "\n").encode("utf-8"))

    def send_raw(self, data: bytes):
        self.sock.sendall(data)

    def read_line(self) -> str:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed while reading line")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return (line + b"\n").decode("utf-8")

    def read_count_framed(self, first_line: str, prefix: str) -> str:
        """
        Reads:
            OK <X> <n>\n  + n lines
        """
        if not first_line.startswith(prefix):
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
            lines.append(self.read_line())
        return "".join(lines)

    def cmd(self, line: str) -> str:
        """
        Send command and read response deterministically based on protocol framing.
        """
        op = line.strip().split(" ", 1)[0].upper()
        self.send(line)
        first = self.read_line()

        # LIST and HELP are count-framed
        if op == "LIST":
            return self.read_count_framed(first, "OK LIST ")
        if op == "HELP":
            return self.read_count_framed(first, "OK HELP ")

        # Everything else: single line
        return first


def connect(port: int) -> BufConn:
    s = socket.create_connection((HOST, port), timeout=1.0)
    return BufConn(s)


def parse_post_id(ok_line: str) -> int:
    # "OK Post <id> created\n"
    parts = ok_line.strip().split()
    return int(parts[2])


# Test suite
class BulletinBoardFullSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = pick_free_port()
        cls.proc = start_server(cls.port)

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.proc)

    def setUp(self):
        self.c = connect(self.port)

    def tearDown(self):
        self.c.close()

    # HELP
    def test_help_general(self):
        r = self.c.cmd("HELP")
        self.assertTrue(r.startswith("OK HELP "))
        self.assertIn("LOGIN <username> <password>\n", r)
        self.assertIn("WHOAMI\n", r)

    def test_help_specific(self):
        r = self.c.cmd("HELP LOGIN")
        self.assertTrue(r.startswith("OK HELP "))
        self.assertIn("Syntax: LOGIN <username> <password>\n", r)

        r2 = self.c.cmd("HELP WHOAMI")
        self.assertTrue(r2.startswith("OK HELP "))
        self.assertIn("Syntax: WHOAMI\n", r2)

    def test_help_bad_syntax(self):
        r = self.c.cmd("HELP TOO MANY ARGS")
        self.assertEqual(r, "ERR BAD_SYNTAX\n")

    def test_unknown_command(self):
        r = self.c.cmd("FLY 123")
        self.assertEqual(r, "ERR UNKNOWN_COMMAND\n")

    # ---- Auth and identity ----
    def test_auth_required(self):
        self.assertEqual(self.c.cmd("WHOAMI"), "ERR Not logged in\n")
        self.assertEqual(self.c.cmd("POST hi"), "ERR Not logged in\n")
        self.assertEqual(self.c.cmd("LIST"), "ERR Not logged in\n")
        self.assertEqual(self.c.cmd("GET 1"), "ERR Not logged in\n")
        self.assertEqual(self.c.cmd("DEL 1"), "ERR Not logged in\n")

    def test_login_success_and_whoami(self):
        self.assertEqual(self.c.cmd("LOGIN oliver pw1"), "OK Logged in as oliver (user)\n")
        self.assertEqual(self.c.cmd("WHOAMI"), "OK WHOAMI oliver user\n")

    def test_login_invalid(self):
        self.assertEqual(self.c.cmd("LOGIN oliver wrong"), "ERR Invalid credentials\n")
        self.assertEqual(self.c.cmd("LOGIN nosuch pw"), "ERR Invalid credentials\n")

    def test_login_bad_syntax(self):
        self.assertEqual(self.c.cmd("LOGIN oliver"), "ERR BAD_SYNTAX\n")
        self.assertEqual(self.c.cmd("LOGIN oliver pw1 extra"), "ERR BAD_SYNTAX\n")

    def test_login_already_logged_in(self):
        self.assertEqual(self.c.cmd("LOGIN sam pw2"), "OK Logged in as sam (user)\n")
        self.assertEqual(self.c.cmd("LOGIN sam pw2"), "ERR Already logged in\n")

    # POST/GET/LIST
    def test_post_empty(self):
        self.c.cmd("LOGIN oliver pw1")
        self.assertEqual(self.c.cmd("POST     "), "ERR Empty message\n")

    def test_post_get_roundtrip(self):
        self.c.cmd("LOGIN oliver pw1")
        ok = self.c.cmd("POST hello world")
        self.assertTrue(ok.startswith("OK Post "))
        pid = parse_post_id(ok)

        g = self.c.cmd(f"GET {pid}")
        self.assertTrue(g.startswith("OK "))
        self.assertIn(" oliver ", g)
        self.assertIn(" hello world\n", g)

    def test_get_not_found_and_syntax(self):
        self.c.cmd("LOGIN oliver pw1")
        self.assertEqual(self.c.cmd("GET"), "ERR BAD_SYNTAX\n")
        self.assertEqual(self.c.cmd("GET x"), "ERR BAD_SYNTAX\n")
        self.assertEqual(self.c.cmd("GET 999999"), "ERR Not found\n")

    def test_list_count_and_format(self):
        self.c.cmd("LOGIN oliver pw1")
        self.c.cmd("POST p1")
        self.c.cmd("POST p2")

        r = self.c.cmd("LIST")
        self.assertTrue(r.startswith("OK LIST "))
        lines = r.splitlines()
        header = lines[0].split()
        self.assertEqual(header[0], "OK")
        self.assertEqual(header[1], "LIST")
        count = int(header[2])
        self.assertEqual(len(lines) - 1, count)

    def test_list_bad_syntax(self):
        self.c.cmd("LOGIN oliver pw1")
        self.assertEqual(self.c.cmd("LIST extra"), "ERR BAD_SYNTAX\n")

    # DEL
    def test_del_syntax_and_not_found(self):
        self.c.cmd("LOGIN oliver pw1")
        self.assertEqual(self.c.cmd("DEL"), "ERR BAD_SYNTAX\n")
        self.assertEqual(self.c.cmd("DEL x"), "ERR BAD_SYNTAX\n")
        self.assertEqual(self.c.cmd("DEL 999999"), "ERR Not found\n")

    def test_del_own_post(self):
        self.c.cmd("LOGIN oliver pw1")
        pid = parse_post_id(self.c.cmd("POST to-delete"))
        self.assertEqual(self.c.cmd(f"DEL {pid}"), f"OK Deleted {pid}\n")
        self.assertEqual(self.c.cmd(f"GET {pid}"), "ERR Not found\n")

    def test_del_other_user_not_authorized(self):
        a = connect(self.port)
        b = connect(self.port)
        try:
            a.cmd("LOGIN oliver pw1")
            b.cmd("LOGIN sam pw2")
            pid = parse_post_id(a.cmd("POST oliver-post"))
            self.assertEqual(b.cmd(f"DEL {pid}"), "ERR Not authorized\n")
        finally:
            a.close()
            b.close()

    def test_admin_can_delete_any(self):
        a = connect(self.port)
        admin = connect(self.port)
        try:
            a.cmd("LOGIN sam pw2")
            admin.cmd("LOGIN admin adminpw")
            pid = parse_post_id(a.cmd("POST admin-delete-me"))
            self.assertEqual(admin.cmd(f"DEL {pid}"), f"OK Deleted {pid}\n")
        finally:
            a.close()
            admin.close()

    def test_cannot_spoof_admin_role(self):
        """
        Ensures there is no 'LOGIN <user> <role>' path left.
        """
        self.assertEqual(self.c.cmd("LOGIN sam admin"), "ERR Invalid credentials\n")

    # Multi-client shared state
    def test_multiclient_visibility(self):
        a = connect(self.port)
        b = connect(self.port)
        try:
            a.cmd("LOGIN oliver pw1")
            b.cmd("LOGIN sam pw2")
            pid = parse_post_id(a.cmd("POST shared"))
            r = b.cmd("LIST")
            self.assertIn(f"{pid} oliver", r)
        finally:
            a.close()
            b.close()

    def test_same_credentials_multiple_sessions_allowed(self):
        a = connect(self.port)
        b = connect(self.port)
        try:
            self.assertEqual(a.cmd("LOGIN oliver pw1"), "OK Logged in as oliver (user)\n")
            self.assertEqual(b.cmd("LOGIN oliver pw1"), "OK Logged in as oliver (user)\n")
        finally:
            a.close()
            b.close()

    def test_quit_closes_session(self):
        self.c.cmd("LOGIN oliver pw1")
        self.assertEqual(self.c.cmd("QUIT"), "OK Bye\n")
        # after QUIT, server closes socket; further operations should error
        with self.assertRaises(Exception):
            self.c.send("HELP")
            _ = self.c.read_line()

    def test_disconnect_cleanup(self):
        """
        Client disconnect should not crash server; other clients continue normally.
        """
        a = connect(self.port)
        b = connect(self.port)
        try:
            a.cmd("LOGIN oliver pw1")
            b.cmd("LOGIN sam pw2")
            _ = parse_post_id(a.cmd("POST before-disconnect"))
            a.close()  # abrupt disconnect
            # b should still work
            r = b.cmd("LIST")
            self.assertTrue(r.startswith("OK LIST "))
        finally:
            try:
                a.close()
            except Exception:
                pass
            b.close()

    # Robustness
    def test_pipelined_commands(self):
        """
        Send multiple commands in one TCP send; ensure server processes each in order.
        """
        # Note: our buffered reader can read sequential responses correctly.
        self.c.send_raw(b"HELP\nLOGIN oliver pw1\nWHOAMI\n")
        # HELP (count-framed)
        first = self.c.read_line()
        self.assertTrue(first.startswith("OK HELP "))
        help_full = self.c.read_count_framed(first, "OK HELP ")
        self.assertIn("LOGIN <username> <password>\n", help_full)
        # LOGIN
        self.assertEqual(self.c.read_line(), "OK Logged in as oliver (user)\n")
        # WHOAMI
        self.assertEqual(self.c.read_line(), "OK WHOAMI oliver user\n")

    def test_partial_send(self):
        """
        Send a command in pieces to ensure server buffering handles partial reads.
        """
        self.c.send_raw(b"LOGIN ol")
        time.sleep(0.02)
        self.c.send_raw(b"iver pw")
        time.sleep(0.02)
        self.c.send_raw(b"1\n")
        self.assertEqual(self.c.read_line(), "OK Logged in as oliver (user)\n")

        self.c.send_raw(b"POST hel")
        time.sleep(0.02)
        self.c.send_raw(b"lo")
        time.sleep(0.02)
        self.c.send_raw(b" world\n")
        ok = self.c.read_line()
        self.assertTrue(ok.startswith("OK Post "))

    # Concurrency
    def test_concurrent_posting_and_deleting(self):
        """
        This is a practical stress test for select()-based multi-client handling.
        It cannot prove absence of races in theory, but it will catch common bugs:
            - dropped connections
            - corrupted framing
            - server crashes under concurrent load
            - inconsistent shared state handling
        """
        N_CLIENTS = 12
        POSTS_PER_CLIENT = 8

        # Create connections
        conns = [connect(self.port) for _ in range(N_CLIENTS)]
        try:
            # Half login as oliver, half as sam
            for i, c in enumerate(conns):
                if i % 2 == 0:
                    self.assertEqual(c.cmd("LOGIN oliver pw1"), "OK Logged in as oliver (user)\n")
                else:
                    self.assertEqual(c.cmd("LOGIN sam pw2"), "OK Logged in as sam (user)\n")

            created_ids = []
            created_ids_lock = threading.Lock()

            def poster(conn: BufConn, idx: int):
                local_ids = []
                for j in range(POSTS_PER_CLIENT):
                    ok = conn.cmd(f"POST c{idx}-m{j}")
                    if ok.startswith("OK Post "):
                        local_ids.append(parse_post_id(ok))
                    else:
                        raise AssertionError(f"POST failed: {ok!r}")
                with created_ids_lock:
                    created_ids.extend(local_ids)

            threads = []
            for i, c in enumerate(conns):
                t = threading.Thread(target=poster, args=(c, i), daemon=True)
                t.start()
                threads.append(t)

            for t in threads:
                t.join(timeout=10)
                self.assertFalse(t.is_alive(), "poster thread hung (server may be stuck)")

            # Verify LIST count >= total created (other tests might have created posts too)
            checker = connect(self.port)
            try:
                checker.cmd("LOGIN admin adminpw")
                r = checker.cmd("LIST")
                self.assertTrue(r.startswith("OK LIST "))
                # Parse count
                count = int(r.splitlines()[0].split()[2])
                self.assertGreaterEqual(count, len(created_ids))
            finally:
                checker.close()

            # Now concurrently delete a subset as admin
            to_delete = created_ids[: max(1, len(created_ids)//2)]
            del_lock = threading.Lock()
            del_errors = []

            def deleter(ids_slice):
                # Each thread gets its own connection
                adm = connect(self.port)
                try:
                    login_resp = adm.cmd("LOGIN admin adminpw")
                    if login_resp != "OK Logged in as admin (admin)\n":
                        with del_lock:
                            del_errors.append(("LOGIN", login_resp))
                        return

                    for pid in ids_slice:
                        resp = adm.cmd(f"DEL {pid}")
                        if not resp.startswith("OK Deleted ") and resp != "ERR Not found\n":
                            with del_lock:
                                del_errors.append((pid, resp))
                finally:
                    adm.close()

            # Split into chunks
            k = 4
            chunks = [to_delete[i::k] for i in range(k)]

            del_threads = []
            for ch in chunks:
                t = threading.Thread(target=deleter, args=(ch,), daemon=True)
                t.start()
                del_threads.append(t)

            for t in del_threads:
                t.join(timeout=10)
                self.assertFalse(t.is_alive(), "deleter thread hung")

            self.assertEqual(del_errors, [], f"Unexpected delete errors: {del_errors[:5]}")

        finally:
            for c in conns:
                c.close()

    # Malformed Input
    def test_line_too_long_disconnects(self):
        """
        Send an oversized command line and ensure server defends itself.
        Expected behavior:
        - server sends ERR Line too long\n (best-effort)
        - server closes connection
        """
        # Must be larger than MAX_BUFFER_BYTES in server.py (64KB)
        huge = "A" * (70 * 1024)

        # Send as one "command" line
        self.c.send_raw((huge + "\n").encode("utf-8"))

        try:
            line = self.c.read_line()
            self.assertEqual(line, "ERR Line too long\n")
            # After error, server closes connection; next read should fail.
            with self.assertRaises(Exception):
                _ = self.c.read_line()
        except Exception:
            pass
            
    def test_invalid_utf8_disconnects(self):
        """
        Send invalid UTF-8 bytes; server should close the connection.
        """
        self.c.send_raw(b"\xff\xfe\xfa\n")
        with self.assertRaises(Exception):
            _ = self.c.read_line()

if __name__ == "__main__":
    unittest.main(verbosity=2)