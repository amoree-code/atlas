"""The browser provider boundary.

Everything above this line is AI-OS: capability, authority, verification, session
identity. Everything below it is one browser technology. A provider is the only place a
browser engine may be named, and swapping one changes nothing above.

A provider is a module exposing the functions below. That is the whole interface — no
registry, no factory, no manager. Selection is `BROWSER_PROVIDER` (default `playwright`),
resolved to `providers/<name>_provider.py` and loaded by explicit path — never through
`sys.path`, which would let a provider file shadow the package it wraps.

    detect()                    -> (ok: bool, detail: str)
    launch(profile_dir, port)   -> dict describing the live session
    connect(session)            -> an opaque handle for the calls below
    close(session)              -> None

    navigate(h, url, timeout)   -> dict
    read_text(h)                -> dict
    observe(h)                  -> dict
    extract(h, selector, attr)  -> dict
    click(h, selector, timeout) -> dict
    type_text(h, selector, text, clear) -> dict
    select(h, selector, value)  -> dict
    scroll(h, dy)               -> dict
    wait_for(h, selector, url_contains, timeout) -> dict
    upload(h, selector, paths)  -> dict
    download(h, selector, dest, timeout) -> dict
    submit(h, selector, timeout)-> dict
    state(h)                    -> dict   # url, title — used by verification

Every call returns a plain dict of JSON-safe values. A provider never decides whether an
action was VERIFIED; it reports what happened and verification re-reads state separately.
"""
