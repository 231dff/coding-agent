---
name: implement
description: Implement a piece of work based on a spec or set of tickets.
trigger: 当需要按规格或 Ticket 实现功能时
category: engineering
disable_model_invocation: true
---

Implement the work described by the user in the spec or tickets.

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, use /code-review to review the work.

Commit your work to the current branch.
