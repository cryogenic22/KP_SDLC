---
description: Explicit broken-window scan. Use when something feels off but no specific bug is in scope.
---

Software entropy: codebases drift toward incoherence unless an active force pushes the other way. This command is that force in slash form.

Walk the working tree (and recent commits if useful) and look for **broken windows** — small rot that's been left to sit. Examples:

- Comments that no longer match the code
- TODO / FIXME / XXX / HACK without a ticket link
- Disabled tests / `xfail` / `skip` without justification in a comment
- Dead code (functions, imports, branches) introduced by previous changes
- Vague-name identifiers (`data`, `info`, `manager`, `helper`, `util`)
- Pass-through methods adding a layer with no abstraction change
- Configuration knobs that aren't actually used anywhere
- Magic numbers without a named constant
- Inconsistent naming between adjacent files (e.g. `userId` here, `user_id` there)
- Imports that exist but aren't used (lint may catch some; check anyway)
- Comments that describe what the code does, not why
- Type-ignore / `# noqa` / `eslint-disable` without inline justification

For each broken window found, recommend ONE of:

1. **Fix now** — small, in-scope, unblocks current work
2. **Open a ticket** — fix is real but out-of-scope; create a TODO with a link to the ticket
3. **Accept** — deliberate decision; document why in a comment so the next reader knows it isn't rot

Do not silently ignore. *That* is what entropy looks like.
