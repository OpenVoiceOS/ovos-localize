# TODO

Known work, with enough context to pick any of it up cold.

## Data lives in git

`data/` holds roughly 500 MB of generated JSON, TSV and JSONL, all of it
rebuilt on a schedule and none of it authored. A fresh clone pays for the
entire history of every regeneration.

The shape of the fix is a build-to-branch pipeline: generate into an ignored
directory, publish the browse JSON to the Pages branch, and keep the training
corpora on Hugging Face, which already hosts them. Write the decision down
before moving anything, because the submission and polling workflows read
`data/` from the checkout and would need repointing.

## Type hints are uneven

Coverage varies by module. Worth raising where it costs nothing, not worth a
sweep of its own.

## Editing is one string at a time

A translator who fixes twenty strings opens twenty issues and produces twenty
pull requests. Issue #139 asks for a session that submits once. The payload
contract for it needs a path validator of its own before it is wired up, since
a batch names many files in one request.

## The stable release path is off

`release_workflow.yml` publishes an alpha from `dev`. Proposing a stable
release is disabled because it opens a pull request against `master`, which
this repository does not have. Create the branch and turn it back on together.
