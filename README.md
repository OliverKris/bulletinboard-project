# Bulletin Board TCP Project

## Overview

This project implements a multi-client Network Bulletin Board service using TCP sockets.

Multiple clients can connect concurrently to a shared server, authenticate, and interact with a common board of posts using a simple text-based protocol.

Each post has:

- a unique ID
- an author (authenticated username)
- a timestamp
- a message body

The server enforces authentication and authorization and supports two roles:

- **Standard user**: may create, list, view, and delete their own posts
- **Administrator**: may create, list, view, and delete any post

The system is designed using a single-threaded, select()-based event loop to safely handle multiple clients concurrently.

## Requirements

To run this project, you will require the following dependencies:

- Python 3.10+
- macOS, Linux, or Windows
- No third-party libraries (Only uses standard libraries)

## How to run

### Start the Server

```bash
python server.py
```

To specify a custom port:

```bash
BBS_PORT=6500 python server.py
```

The server will then print:

```bash
Server listening on 0.0.0.0:<port>
```

### Start a Client

```bash
python client.py
```

The client provides a simple REPL for interacting with the server.

### Run Tests

```bash
python tests.py
```

The test suite:

- launches the server automatically on a random port
- tests protocol correctness, authentication, authorization
- validates multi-client behavior
- stress-tests concurrency and partial sends
- checks robustness against malformed input

## Protocol Specifications

### Transport Framing

- Transport: **TCP**
- Encoding: **UTF-8 text**
- Commands are **newline-terminated** (``\n``)
- Server responses:
  - Most commands return **a single line** ending in ``\n``
  - ``LIST`` and ``HELP`` return **count-framed multi-line responses**

### Count-Framed Responses

Both ``LIST`` and ``HELP`` return special count-framed responses in the following formats:

#### LIST

```php-template
OK LIST <count>\n
<id> <author> <timestamp> <message>\n   (repeated <count> times)
```

#### HELP

```php-template
OK HELP <count>\n
<line 1>\n
<line 2>\n
...
```

This framing ensures clients can deterministically read multi-line responses.

## Session Semantics

- Authentication is **per TCP connection**
- Clients must ``LOGIN`` before using:
- ``POST``, ``LIST``, ``GET``, ``DEL``, ``WHOAMI``
- ``QUIT`` terminates the session and closes the connection
- Multiple simultaneous sessions using the same username are **allowed**

## Commands

### HELP

```php-template
HELP
HELP <command>
```

Displays general help or command-specific usage.

### LOGIN

```php-template
LOGIN <username> <password>
```

Validates credentials against a server-side user database
Assigns role **server-side** (client cannot choose role)

Errors:

- ``ERR BAD_SYNTAX``
- ``ERR Invalid credentials``
- ``ERR Already logged in``

### WHOAMI

```php-template
WHOAMI
```

Returns:

```php-template
OK WHOAMI <username> <role>
```

### POST

```php-template
POST <message...>
```

Message is the entire rest of the line (spaces preserved)

Errors:

- ``ERR Not logged in``
- ``ERR Empty message``

### LIST

```php-template
LIST
```

Returns all posts in ascending ID order.

### GET

```php-template
GET <id>
```

Errors:

- ``ERR BAD_SYNTAX``
- ``ERR Not found``

### DEL

```php-template
DEL <id>
```

Authorization:

- Admin: may delete any post
- User: may delete only their own posts

Errors:

- ``ERR BAD_SYNTAX``
- ``ERR Not found``
- ``ERR Not authorized``

### QUIT

```php-template
QUIT
```

Returns:

```php-template
OK Bye
```

Then closes the connection.

## Error Responses

All error responses are **single-line**, newline-terminated:

- ``ERR UNKNOWN_COMMAND``
- ``ERR BAD_SYNTAX``
- ``ERR Not logged in``
- ``ERR Invalid credentials``
- ``ERR Already logged in``
- ``ERR Empty message``
- ``ERR Not found``
- ``ERR Not authorized``
- ``ERR Line too long``

## Security Model

- Password validation is performed **server-side**
- Roles are assigned from a trusted server user database
- Clients cannot spoof roles or bypass authorization
- Delete permissions are enforced strictly on the server

## Concurrency Model

- The server uses a **single-threaded** ``select()`` event loop
- Each client has its own input buffer
- Commands are processed **only after a full line is received**
- Shared board state is mutated only inside the event loop
- This design avoids race conditions without explicit locks

## Robustness and Defensive Handling

- Partial TCP sends are handled correctly via per-client buffering
- Invalid UTF-8 input results in connection termination
- Oversized input lines are rejected with:

    ```php-template
    ERR Line too long
    ```

    and the client is disconnected to prevent memory exhaustion

## Example Session

```markdown
> HELP
OK HELP 13
LOGIN <username> <password>
POST <message...>
LIST
GET <id>
DEL <id>
WHOAMI
HELP [command]
QUIT
...

> LOGIN oliver pw1
OK Logged in as oliver (user)

> POST hello world
OK Post 1 created

> LIST
OK LIST 1
1 oliver 2025-12-17T14:22:01 hello world

> WHOAMI
OK WHOAMI oliver user

> QUIT
OK Bye
```

### Known Limitations

- Posts are stored in memory only (no persistence)
- Communication is plaintext TCP (no encryption)

## Summary

This project demonstrates:

- practical TCP socket programming
- custom application-level protocol design
- multi-client concurrency using ``select()``
- authentication and authorization enforcement
- defensive handling of malformed or malicious input

It is intentionally designed to be extensible into a REST API or persistent service with minimal changes.
