# Your workspace

`$ATLAS_HOME` is private (default `~/atlas`). Atlas reads and updates it during setup, but
never publishes it or overwrites existing user files.

## Main layout

```text
$ATLAS_HOME/
├── personal/       memory, knowledge, daily records, templates
├── projects/       project registry and project-owned state
├── system/         config, governance rules and policies
├── extensions/     personal skills and agents
├── helpers/        local helper scripts when configured
├── schemas/        private schemas when configured
└── runtime/        sessions and transient generated state
```

This is a guide, not a creation recipe. Workspace versions and existing data can add
directories. Use `atlas root` and `atlas paths list` to resolve the current locations.

## The important boundaries

- `personal/` holds durable human-facing data.
- `projects/` holds state belonging to one project.
- `system/` holds machine-facing configuration and governance.
- `runtime/` holds temporary or session-scoped state.

The public engine clone is separate from all of these. Read [Public and private](../design/public-private.md)
for the reason behind the split.

## Templates

`atlas setup` seeds files only when their destination does not exist. After that, your file
and the public template are independent. Updating a template never overwrites your copy;
rerun `atlas setup preflight` to see what the current setup would do.

## Skills and agents

Personal extensions take precedence over public extensions:

```text
$ATLAS_HOME/extensions/skills -> <engine>/extensions/skills
$ATLAS_HOME/extensions/agents -> <engine>/extensions/agents
```

Public extensions are not copied into the private workspace. `atlas doctor` reports
shadowing or boundary problems.

## Related commands

```bash
atlas root
atlas paths list
atlas status
atlas structure check
atlas doctor
```

See [Memory](memory.md), [Projects](projects.md), and [Safety](safety.md) for the data,
scope, and versioning rules.
