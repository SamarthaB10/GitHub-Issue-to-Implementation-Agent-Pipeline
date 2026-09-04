---
status: accepted
---

# Portable worker skill snapshots

The project will maintain a portable skill catalog with repository-relative
links. It will copy complete, reviewed directories for the worker skill bundle,
keep source and version metadata, and refresh them only through an explicit user
action; the catalog may reference the wider local skill set without loading all
skill instructions into every worker context. This preserves reproducible
worker behavior across cloned project workspaces while keeping unrelated skills
out of the implementation runtime.
