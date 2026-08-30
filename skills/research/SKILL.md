---
name: research
description: Research a technology, library, tool, or technical decision and file the result as a structured knowledge note. Use when the user says research, compare, evaluate, should I use X, look into, or what is the best way to.
---

# Research

Produce a decision, not a link dump.

## Steps

1. **Frame the question.** State it in one line and confirm it's the real question. "Should
   I use X?" is usually "what should I use for Y, given my stack?" — answer that one.

2. **Search.** Prefer primary sources: official docs, the repo, release notes, RFCs. Check
   dates — an answer that was true two years ago is often wrong now. Check the library's
   last release and open-issue trend before recommending it.

3. **Ground it in the actual stack.** Read the user's recorded stack conventions
   (`~/.ai-os/config/models.yaml` or `~/.ai-os/memory/preferences/`) and, if a specific
   project prompted this, that project's context file. A recommendation that ignores the
   user's actual stack is not useful.

4. **Answer in chat first** — recommendation, the two or three reasons, and the main
   trade-off being accepted. Lead with the answer.

5. **File it** only if it has lasting value (a decision made, a tool adopted or rejected,
   a pattern worth keeping). Write it under `~/.ai-os/knowledge/research/<topic>.md`. A
   throwaway lookup gets no file.

6. If it settles a real technical decision, also record it in
   `~/.ai-os/knowledge/decisions/`.

## Rules

- **Distinguish what you verified from what you're inferring.** Say which is which.
- Give a recommendation. "It depends" is only acceptable with the deciding factor named.
- Report a version number only if you saw it in this session's sources.
- Don't browse when you already know the answer, and don't file a note to look thorough.
