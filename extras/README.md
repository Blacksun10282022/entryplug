# extras · where connector side-scripts live

Transcription (bilibili → text), a WeChat export, pulling text out of a pdf or epub: connectors go here. They are
side-scripts — run one when you want to. They do not count towards the machine's line budget, they are not
tested, and `plug` never calls them. All they produce is text files you drop into the content repo's
`corpus/raw/` or `materials/`; being in the index is not the same as being equipment.

Empty in this version. A connector's config (accounts, cookies, paths) is never committed —
`tests/test_no_leak.py` catches it.
