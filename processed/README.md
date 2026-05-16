# processed/ — consumed inputs archive

Frozen archive. Every file here was once in `unprocessed/` and has since been
folded into the wiki by an integrate pass (see
[`../unprocessed/README.md`](../unprocessed/README.md)).

Structure mirrors `unprocessed/` (`uploads/`, `transcripts/`, `notes/`).

**Never edit anything here.** It exists so that a wiki citation of the form
`[src: processed/...]` always resolves, and so you can audit what fed which
wiki change (cross-reference the `## [date] integrate` entries in
`wiki/log.md`).
