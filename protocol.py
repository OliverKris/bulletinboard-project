# protocol.py
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from typing import Optional

ph = PasswordHasher()

_SEEDED_PLAINTEXT_USERS = {
    "oliver": {"password": "pw1", "role": "user"},
    "sam":   {"password": "pw2", "role": "user"},
    "admin": {"password": "adminpw", "role": "admin"},
}

def _hash_seeded_users() -> dict:
    users = {}
    for username, rec in _SEEDED_PLAINTEXT_USERS.items():
        users[username] = {
            "pw_hash": ph.hash(rec["password"]),
            "role": rec["role"],
        }
    return users

USERS = _hash_seeded_users()

def register(username: str, password: str) -> tuple[bool, str]:
    if username in USERS:
        return False, "ERR username_taken"
    if len(password) < 10:
        return False, "ERR password_too_short"
    
    pw_hash = ph.hash(password)
    USERS[username] = {"pw_hash": pw_hash}
    return True, "OK registered"

def verify_password(record: dict, password: str) -> bool:
    stored_hash = record.get("pw_hash")
    if not stored_hash:
        return False

    try:
        ok = ph.verify(stored_hash, password)
    except VerifyMismatchError:
        return False
    return True

class Post:
    def __init__(self, post_id, author, timestamp, message):
        self.id = post_id
        self.author = author
        self.timestamp = timestamp
        self.message = message

posts: dict[int, Post] = {}
next_post_id = 1

def require_auth(client) -> Optional[str]:
    if not getattr(client, "authenticated", False):
        return "ERR Not logged in\n"
    return None

def handle_help(client, rest):
    """
    HELP
    HELP <CMD>

    Always returns a count-framed response:
        OK HELP <n>\n
        <n> lines follow
    """
    arg = rest.strip()

    if arg == "":
        body = [
            "LOGIN <username> <password>",
            "POST <message...>",
            "LIST",
            "GET <id>",
            "DEL <id>",
            "WHOAMI",
            "HELP [command]",
            "QUIT",
            "EXAMPLES:",
            "  LOGIN oliver pw1",
            "  POST hello world",
            "  LIST",
            "  GET 1",
            "  DEL 1",
            "  WHOAMI",
            "  QUIT",
        ]
        return "OK HELP " + str(len(body)) + "\n" + "\n".join(body) + "\n"

    parts = arg.split()
    if len(parts) != 1:
        return "ERR BAD_SYNTAX\n"

    cmd = parts[0].upper()

    details = {
        "LOGIN": [
            "TOPIC: LOGIN",
            "Syntax: LOGIN <username> <password>",
            "Notes: Must be called before POST/LIST/GET/DEL/WHOAMI.",
        ],
        "POST": [
            "TOPIC: POST",
            "Syntax: POST <message...>",
            "Notes: Author is your authenticated username; message is the rest of the line.",
        ],
        "LIST": [
            "TOPIC: LIST",
            "Syntax: LIST",
            "Response: OK LIST <count> followed by <count> post lines.",
        ],
        "GET": [
            "TOPIC: GET",
            "Syntax: GET <id>",
        ],
        "DEL": [
            "TOPIC: DEL",
            "Syntax: DEL <id>",
            "Notes: Allowed if you are admin or you are the post author.",
        ],
        "WHOAMI": [
            "TOPIC: WHOAMI",
            "Syntax: WHOAMI",
            "Response: OK WHOAMI <username> <role>",
        ],
        "HELP": [
            "TOPIC: HELP",
            "Syntax: HELP",
            "        HELP <command>",
        ],
        "QUIT": [
            "TOPIC: QUIT",
            "Syntax: QUIT",
            "Notes: Server will close the connection after responding.",
        ],
    }

    if cmd not in details:
        return "ERR UNKNOWN_COMMAND\n"

    body = details[cmd]
    return "OK HELP " + str(len(body)) + "\n" + "\n".join(body) + "\n"

def handle_whoami(client, rest):
    """
    WHOAMI
    """
    err = require_auth(client)
    if err:
        return err
    if rest.strip():
        return "ERR BAD_SYNTAX\n"
    return f"OK WHOAMI {client.username} {client.role}\n"

def handle_login(client, rest):
    """
    LOGIN <username> <password>

    - Reject if already logged in
    - Validate username/password against USERS (Argon2)
    - Assign role from USERS[username]["role"]
    """
    if getattr(client, "authenticated", False):
        return "ERR Already logged in\n"

    parts = rest.split()
    if len(parts) != 2:
        return "ERR BAD_SYNTAX\n"

    username, password = parts
    record = USERS.get(username)
    if record is None:
        # Keep message generic (avoid user enumeration)
        return "ERR Invalid credentials\n"

    if not verify_password(record, password):
        return "ERR Invalid credentials\n"

    client.username = username
    client.role = record.get("role", "user")
    client.authenticated = True
    return f"OK Logged in as {username} ({client.role})\n"

def handle_post(client, rest):
    """
    POST <message...>
    Message is the entire rest string (preserve spacing),
    but must not be empty/whitespace-only.
    """
    global next_post_id, posts

    err = require_auth(client)
    if err:
        return err

    if not rest.strip():
        return "ERR Empty message\n"

    post_id = next_post_id
    next_post_id += 1

    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    message = rest  # preserve original rest

    post = Post(post_id, client.username, ts, message)
    posts[post_id] = post

    return f"OK Post {post_id} created\n"

def handle_list(client, rest):
    """
    LIST
    Enforce no args (keeps protocol predictable for testing).
    """
    err = require_auth(client)
    if err:
        return err

    if rest.strip():
        return "ERR BAD_SYNTAX\n"

    lines = [f"OK LIST {len(posts)}"]
    for post_id in sorted(posts.keys()):
        p = posts[post_id]
        lines.append(f"{p.id} {p.author} {p.timestamp} {p.message}")
    return "\n".join(lines) + "\n"

def handle_get(client, rest):
    """
    GET <id>
    """
    err = require_auth(client)
    if err:
        return err

    parts = rest.split()
    if len(parts) != 1:
        return "ERR BAD_SYNTAX\n"

    try:
        post_id = int(parts[0])
    except ValueError:
        return "ERR BAD_SYNTAX\n"

    post = posts.get(post_id)
    if post is None:
        return "ERR Not found\n"

    return f"OK {post.id} {post.author} {post.timestamp} {post.message}\n"

def handle_del(client, rest):
    """
    DEL <id>
    Only allowed if:
    - client.role == 'admin' OR
    - post.author == client.username
    """
    err = require_auth(client)
    if err:
        return err

    parts = rest.split()
    if len(parts) != 1:
        return "ERR BAD_SYNTAX\n"

    try:
        post_id = int(parts[0])
    except ValueError:
        return "ERR BAD_SYNTAX\n"

    post = posts.get(post_id)
    if post is None:
        return "ERR Not found\n"

    if client.role != "admin" and post.author != client.username:
        return "ERR Not authorized\n"

    del posts[post_id]
    return f"OK Deleted {post_id}\n"

def handle_quit(client, rest):
    if rest.strip():
        return "ERR BAD_SYNTAX\n"
    return "OK Bye\n"

COMMANDS = {
    "HELP":   (handle_help, False),
    "LOGIN":  (handle_login, False),
    "POST":   (handle_post, False),
    "LIST":   (handle_list, False),
    "GET":    (handle_get, False),
    "DEL":    (handle_del, False),
    "WHOAMI": (handle_whoami, False),
    "QUIT":   (handle_quit, True),
}

def process_line(client, line):
    if line is None:
        return (None, False)

    if line == "":
        return (None, False)

    parts = line.split(" ", 1)
    cmd = parts[0].upper()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd not in COMMANDS:
        return ("ERR UNKNOWN_COMMAND\n", False)

    handler, should_close = COMMANDS[cmd]
    response = handler(client, rest)
    return (response, should_close)