---
status: accepted
---

# Chief tickets and Runtime Skill traces

Chief will use `to-tickets` to convert the human-approved plan into
dependency-aware WorkerTask queue entries. Runtime workers will not have
separate implementation roles such as cleanup or review; every implementation
worker will follow the same `implement → tdd → code-review` route. Each worker
will return a Skill trace, and Chief will gate WorkerResult acceptance on the
required trace phases and result evidence.
