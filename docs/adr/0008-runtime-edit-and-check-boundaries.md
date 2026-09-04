---
status: accepted
---

# Runtime edit and check boundaries

Runtime workers will change files through atomic, hash-checked patch
operations. Paths must stay inside the assigned Worktree and assigned scope;
path escapes, symlink escapes, product control files, binary edits, and
permission changes are rejected. Runtime checks will use exact approved
argument lists, a fixed Worktree directory, bounded time and output, a
sanitised environment, and no package installation or network access by
default.
