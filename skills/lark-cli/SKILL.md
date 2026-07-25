---
name: lark-cli
description: Use the locally installed `lark-cli` to query and operate Feishu/Lark services from Codex. Use when the user asks to work with Feishu/Lark messages, chats, docs, Drive files, Wiki, Base, Sheets, Slides, Calendar, Tasks, Mail, Contacts, approvals, OKR, meetings, minutes, attendance, or raw Feishu OpenAPI calls through the terminal.
---

# Lark CLI

## Core Workflow

1. Verify the local tool before acting:

```bash
command -v lark-cli
lark-cli --version
lark-cli doctor
lark-cli auth status
```

2. Inspect help before using an unfamiliar command. Do not assume every subcommand accepts `--format`, `--params`, `--data`, or pagination flags.

```bash
lark-cli --help
lark-cli <service> --help
lark-cli <service> <command> --help
```

3. Prefer the highest-level command that fits the task:

- Shortcut commands such as `calendar +agenda`, `im +messages-send`, and `docs +fetch` for common workflows.
- API commands such as `calendar events instance_view --params '{...}'` when a shortcut is not precise enough.
- Raw API calls such as `api GET /open-apis/...` only when the generated API command is missing or unsuitable.

4. Use `lark-cli schema` before constructing complex API commands:

```bash
lark-cli schema
lark-cli schema calendar.events.instance_view
lark-cli schema im.messages.delete
```

5. For commands that mutate Feishu/Lark state, preview first when supported:

```bash
lark-cli im +messages-send --chat-id "oc_xxx" --text "hello" --dry-run
```

Then run the real command only after the target, identity, and payload are clear. For high-impact actions such as deleting, bulk updating, sending messages to many recipients, changing permissions, or approving/rejecting workflows, ask the user for explicit confirmation before execution.

## Output Handling

- Prefer JSON output for machine processing when the command supports it: `--format json`.
- Use `--jq` or `-q` to reduce large JSON responses at the CLI layer.
- Use `--format table`, `pretty`, `csv`, or `ndjson` only when they fit the user-facing result.
- Use `--page-all` plus `--page-limit` for searches and list operations that may paginate. Avoid unbounded pagination unless the user explicitly asks.
- Keep credentials, tokens, private chat content, and personal data out of final answers unless the user specifically requested that exact data.

## Identity And Auth

Run `lark-cli auth status` before commands that depend on user identity. If status reports only bot/tenant identity, use bot-compatible commands or ask the user to log in with:

```bash
lark-cli auth login --recommend
```

Use identity flags intentionally:

```bash
lark-cli calendar +agenda --as user
lark-cli im +messages-send --as bot --chat-id "oc_xxx" --text "Hello"
```

If a command fails for missing scopes, inspect available scopes and re-auth only for the needed domain:

```bash
lark-cli auth scopes
lark-cli auth check <scope>
lark-cli auth login --domain calendar,task
```

## Common Domains

Use `lark-cli <domain> --help` to discover exact shortcuts and flags. Common domains include:

- `calendar`: agenda, events, attendees, free/busy, room search, RSVP.
- `im`: messages, replies, chat search, chat creation/update, message resources.
- `docs`: create, fetch, update, search, media upload/download.
- `drive`: files, upload/download, permissions, comments.
- `markdown`: native Markdown files in Drive.
- `base`: Base tables, fields, records, views, dashboards, forms, roles.
- `sheets`: spreadsheet read/write/append/find/export.
- `slides`: presentations and slide pages.
- `task`: tasks, task lists, subtasks, reminders, comments.
- `mail`: search/read/send/reply/forward mail and drafts.
- `contact`: search users and get user info.
- `wiki`: spaces, nodes, and documents.
- `vc` and `minutes`: meeting records, minutes, summaries, action items, transcripts.
- `approval`: approval tasks and instances.
- `okr`, `attendance`, `whiteboard`, `event`: specialized Lark domains.

Read `references/command-patterns.md` when you need examples for command selection, JSON quoting, pagination, raw OpenAPI calls, or troubleshooting.
