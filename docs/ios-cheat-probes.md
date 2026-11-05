# Tears of the Kingdom 1.4.3 iOS cheat probes

Status: **experimental; gameplay validation pending**. The iOS settings screen exposes three independent switches,
off by default. A saved choice is published to the game's private data page after the corresponding hook passes its
checks. These hooks follow the reference app's observed behavior; their gameplay coverage and effect on unrelated
objects have not been independently established.

The original `main` extracted from the 1.4.3 NSP matches the repository's ExeFS hash, and its rewritten image matches
the recorded rewrite hash. The three candidate sites are `main+0x4407d0` (health), `main+0x782274` (battery) and
`main+0x31d398` (stamina). The reference IPA's static behavior is the starting point, not evidence that these sites
only affect Link. In particular, the health site's caller and object fields have not been identified in live gameplay.
In the original code the health hook receives the object at `[x19+0x1830]`; nearby code reads and writes its `+8` field
while comparing it with related objects at `+0x1838`, `+0x1840` and `+0x1848`. The stamina instruction updates the float
at `[x19+0x74]`, while the battery path reads or writes `[x19+0x44]`. These observations establish the surrounding data
flow, not the identities of the objects or the full set of callers.

The iOS export emits separate veneers in the zero-padded tail of the rewritten patch area and guards the three original
words and the veneer space. The iOS loader checks the exported instructions before guest execution. An absent site leaves
its original instruction alone; a branch into a damaged veneer stops the loader because signed executable pages cannot
be repaired at runtime. The Windows export verifier exercises both cases. With the flags zero, the stamina veneer executes
the original floating-point instruction, the health veneer performs the original load, and the battery veneer follows
the original conditional branch. No gameplay value is intentionally modified in this state.

`tests/test_ios_cheat_probes.py` executes the actual Windows-exported instructions under Unicorn, with flags both on and
off, checking the continuations, registers, condition flags and synthetic memory changes. Set `TOTK_CHEAT_EXPORTED` to the
local export directory and make Unicorn available to Python to run it. All eight combinations of the three flags are
covered, including the original battery branch in both directions. This is an instruction-level test only: it does
not establish that an enabled probe is player-specific, safe for all game states, or effective during actual play.

Trace each site's data and owners in the actual 1.4.3 game, verify player identity and unrelated objects, then test the
three features independently and together across damage, movement, Zonai use, loading, death and scene transitions on a
disposable save. Record coverage and unsupported paths. iPhone validation remains necessary; the IPA is unsigned and is
not installed by the build.
