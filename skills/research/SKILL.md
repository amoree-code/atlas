---
name: research
description: Research a technology, library, tool, or technical decision and file the result as a structured intelligence note. Use when the user says research, compare, evaluate, should I use X, look into, or what is the best way to.
---

# Research

Produce a decision, not a link dump.

## Steps

1. **Frame the question.** State it in one line and confirm it's the real question. "Should
   I use X?" is usually "what should I use for Y, given my stack?" — answer that one.

2. **Search.** Prefer primary sources: official docs, the repo, release notes, RFCs. Check
   dates — an answer that was true two years ago is often wrong now. Check the library's
   last release and open-issue trend before recommending it.

3. **Ground it in the actual stack.** Read
   `{{profile.stack.doc}}` and, if a specific project prompted this,
   its `{{client.project_context}}`. A recommendation that ignores {{profile.stack.summary}} is not useful here.

4. **Answer in chat first** — recommendation, the two or three reasons, and the main
   trade-off being accepted. Lead with the answer.

5. **File it** only if it has lasting value (a decision made, a tool adopted or rejected,
   a pattern worth keeping). Write `~/.ai-os/user/05-knowledge/research/<topic>.md`. A throwaway
   lookup gets no file. (Not `intelligence/` — that layer is deprecated, superseded by
   `knowledge/` since the 2026-08-30 memory/knowledge split.)

6. If it settles a real technical decision, also record it: cross-project →
   `~/.ai-os/user/05-knowledge/decisions/`; one project → that repo's `{{client.project_memory}}decisions.md`.

## Rules

- **Distinguish what you verified from what you're inferring.** Say which is which.
- Give a recommendation. "It depends" is only acceptable with the deciding factor named.
- Report a version number only if you saw it in this session's sources.
- Don't browse when you already know the answer, and don't file a note to look thorough.
