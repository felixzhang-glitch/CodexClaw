# Lark CLI Command Patterns

Source: https://github.com/larksuite/cli/blob/main/README.zh.md and local `lark-cli --help`.

## Command Selection

Use this order:

1. Shortcut: `lark-cli <service> +<action> ...`
2. Generated API command: `lark-cli <service> <resource> <method> --params '{...}' --data '{...}'`
3. Raw OpenAPI: `lark-cli api <METHOD> /open-apis/<path> --params '{...}' --data '{...}'`

Examples:

```bash
lark-cli calendar +agenda
lark-cli im +messages-send --chat-id "oc_xxx" --text "Hello"
lark-cli docs +fetch --help
lark-cli calendar events instance_view --params '{"calendar_id":"primary","start_time":"1700000000","end_time":"1700086400"}'
lark-cli api GET /open-apis/calendar/v4/calendars
```

## JSON Quoting

Prefer single quotes around JSON in shell commands:

```bash
lark-cli api POST /open-apis/im/v1/messages \
  --params '{"receive_id_type":"chat_id"}' \
  --data '{"receive_id":"oc_xxx","msg_type":"text","content":"{\"text\":\"Hello\"}"}'
```

For multiline document content in zsh/bash, use `$'...'` when needed:

```bash
lark-cli docs +create --api-version v2 --doc-format markdown \
  --content $'<title>周报</title>\n# 本周进展\n- 完成 X'
```

## Discovery

Use help and schema instead of guessing:

```bash
lark-cli <service> --help
lark-cli <service> <command> --help
lark-cli schema <service.resource.method>
```

Useful service discovery commands:

```bash
lark-cli calendar --help
lark-cli im --help
lark-cli docs --help
lark-cli base --help
lark-cli sheets --help
lark-cli task --help
lark-cli contact --help
```

## Output And Pagination

Supported output formats on many commands:

```bash
--format json
--format pretty
--format table
--format ndjson
--format csv
```

Not every subcommand supports these flags. If a flag fails, rerun `--help` for that exact command.

For list/search commands:

```bash
--page-all
--page-limit 5
--page-delay 500
--page-size 50
```

Keep result sets bounded unless the user asked for a full export.

## Auth And Identity

Check state:

```bash
lark-cli auth status
lark-cli auth list
```

Login or adjust scopes:

```bash
lark-cli auth login
lark-cli auth login --recommend
lark-cli auth login --domain calendar,task
lark-cli auth login --scope "calendar:calendar:read"
```

Use `--as user`, `--as bot`, or `--as auto` when the identity matters. If the current account is bot-only, user-only operations such as personal agenda or user-visible message search may fail until the user completes OAuth login.

## Safety

Use `--dry-run` for writes when supported. Treat these as high-impact and ask for confirmation before the final command:

- Sending messages to chats or users.
- Creating, updating, or deleting docs, records, sheets, tasks, events, permissions, comments, approvals, OKRs, or mails.
- Bulk operations, exports of sensitive data, or operations across many recipients.
- Any raw `api POST`, `PATCH`, `PUT`, or `DELETE` call.

## Troubleshooting

Run:

```bash
lark-cli doctor
lark-cli auth status
lark-cli <service> <command> --help
lark-cli schema <method>
```

Common failure modes:

- `unknown flag`: that exact subcommand does not support the flag; inspect its help.
- missing scope/permission: check `auth status`, `auth scopes`, and re-login with the minimum needed domain/scope.
- identity mismatch: retry with `--as user` or `--as bot` only if that identity is appropriate for the task.
- malformed JSON: validate shell quoting and prefer compact single-quoted JSON.
