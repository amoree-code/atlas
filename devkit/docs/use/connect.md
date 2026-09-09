# Connecting any MCP client

Known client:

```bash
atlas connect <id> --approve
```

Unknown client with a JSON MCP config:

```bash
atlas connect --client deepseek --json-config ~/.deepseek/config.json --approve
```

The command starts the Atlas gateway handshake, reads `tools/list`, then registers the
gateway. It prefers the client's native MCP command. The generic JSON path writes only the
declared object key and preserves a timestamped backup.

```text
client → native MCP command or explicit JSON recipe → Atlas MCP gateway → tools/list
```

MCP makes the server protocol common. It does not standardize where every client stores its
configuration, so an unknown client must provide its config path or native registration
command. Atlas never guesses that path.
