"""The weather-lookup provider boundary — illustration only, modelled on
capabilities/browser/providers/interface.py.

Everything above this line would be Atlas: capability, authority, verification, result
shape. Everything below it is one weather-data source. A provider is the only place that
source is named, and swapping it would change nothing above.

A provider is a module exposing the functions below. That is the whole interface — no
registry, no factory, no manager.

    detect()                  -> (ok: bool, detail: str)
    forecast(location, days)  -> dict   # JSON-safe; never claims verification itself

This fictional capability ships no provider and no command file — there is nothing here
to select between and nothing that runs. A real capability following this shape would add
`providers/<name>_provider.py` implementing these functions, plus a `command:` script
(see `capabilities/browser/browser`) that loads one by name.
"""
