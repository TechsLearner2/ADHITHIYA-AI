# ASTRA: The Asura War v7 — bug hunt report

**File:** `astra/ASTRA_The_Asura_War_v7.html` (original upload: `ASTRA_The_Asura_War_v7.html`, 958 KB)
**Method:** static parse (Acorn / Babel / ESLint `no-undef`) + a headless jsdom harness that stubs
canvas + WebAudio, boots the page, clicks START, drives real input events and steps the game loop
frame by frame for thousands of frames (waves, bosses, boons, divine aid, ultimates, pause, restart).

---

## Summary

| # | Severity | Bug | Status |
|---|----------|-----|--------|
| 1 | **Blocker** | `const SEED=0xBHARATA;` — invalid numeric literal, the entire game `<script>` fails to parse | fixed |
| 2 | **Blocker** | Missing `}` closing `beginRitual()` — second parse error in the same block | fixed |
| 3 | **Blocker** | `let diffMode` declared twice in the same scope | fixed |
| 4 | **Blocker** | Malformed `<div id="bossPanel"` tag swallows `#diffBadge` and `#battleLog`; `reset()` throws → **pressing START did nothing** | fixed |
| 5 | High | `gv` is never declared (used in `soldierTick`) — throws every frame once a citizen is rescued with a rishi nearby | fixed |
| 6 | High | `_sc = zScale(...)` — implicit global inside `"use strict"` `draw()` | fixed |
| 7 | High | `mf2()` defined inside the `SINGER` IIFE but called from `synthesizeMantra()` (3 sites) | fixed |
| 8 | Medium | `ritual.se = buf.duration / sampleRate` — wrong unit, mantra screen auto-ends after ~1 frame | fixed |
| 9 | Medium | Inline `onclick="openHow()" / "setDiff('hard')"` handlers point at IIFE-scoped functions | fixed |
| 10 | Low | `#diffBadge`/`#battleLog` are `position:fixed` but were nested inside the HUD (cosmetic) | fixed with #4 |
| 11 | Low | `#mSkip` ("TAP TO CONTINUE") is a purely decorative div with no click handler | open (by design? tap-anywhere works) |

Everything below is reproducible; the harness output is quoted where it matters.

---

## 1 — Blocker: the whole game script never parses

```js
// line 1383 (menu canvas engine)
const SEED=0xBHARATA;
```

`0xBHARATA` is not a hex literal (`H`, `R`, `T` are not hex digits). One bad token kills the **entire**
`<script>` block, so *nothing* in the game boots — no menu animation, no canvas, no button wiring.

```
$ node --check game.js
game.js:1098
 const SEED=0xBHARATA;
            ^^^
SyntaxError: Invalid or unexpected token
```

Harness on the untouched file:

```
SyntaxError: Invalid or unexpected token
hud:  | hp: 100 / 100 | kills: 0 | wave: 01 | time: 00:00     <- game never started
```

**Fix applied:** `const SEED=0x0BAD1A55;` (any valid literal works; the value only seeds the menu
diagram's procedural world).

## 2 — Blocker: `beginRitual()` is missing its closing brace

```js
function beginRitual(g){ ... 
 const M=$('mantra');M.style.setProperty('--gc',g.color);M.className='on';
 requestAnimationFrame(()=>requestAnimationFrame(()=>M.classList.add('show')))}
 function tickRitual(dt){ ...
```

The `}` at the end of that line closes the inner `if(x){…}`, not the function, so every function after
it (`tickRitual`, `finishRitual`, `sound`, `genLayout`, …) is parsed as nested and the wrapper's final
`)();` no longer matches. Masked by bug #1 because the file already failed earlier.

**Fix applied:** added the missing `}`.

## 3 — Blocker: duplicate declaration

```js
let diffMode='normal';      // line 1269
function setDiff(m){ … }
```
`diffMode` is already declared in the big `let …` list at the top (line 9) →
`SyntaxError: Identifier 'diffMode' has already been declared`.

**Fix applied:** removed the second `let`, kept the initial value from the top-level declaration.

## 4 — Blocker: a malformed tag means START does nothing

Line 209–212 of the HTML:

```html
<div id="bossPanel"
<div id="diffBadge"></div>
<div id="battleLog"></div>
><div id="bossName">RAVANA · TEN-HEADED KING</div> …
```

A newline inside a start tag is legal, so the parser keeps consuming and creates

```
<div id="bossPanel" <div=""></div>      <-- #diffBadge attribute-junk'd, badge never exists
```

`#diffBadge` ends up **outside the document's element index** and `reset()` does
`$('diffBadge').textContent=…` on `null`:

```
TypeError: Cannot set properties of null (setting 'textContent')
    at reset (…:307:252)
    at HTMLButtonElement.start (…:924:260)
```

Because `reset()` throws, `start()` aborts *before* `active=true`, `hud.style.display='block'` and the
first `requestAnimationFrame` — **clicking START just flickers the menu and returns**. Harness on the
original:

```
hud:  | hp: 100 / 100 | kills: 0 | wave: 01 | time: 00:00
```

**Fix applied:**

```html
<div id="diffBadge"></div>
<div id="battleLog"></div>
<div id="bossPanel"><div id="bossName">…
```

Both elements are `position:fixed` in CSS, so moving them out of the HUD keeps their intended layout
(and fixes #10 for free). After the fix: `frames run … hud: block | hp: 120 / 120 | kills: 2 |
wave: 01 | time: 00:06`.

## 5 — High: `gv` is not defined

```js
// soldierTick(), line 781
n.tr=(n.tr||0)+dt*(.6+saints.length*.4)*gv;
```

`gv` does not exist anywhere in the file. In strict mode this throws on **every frame** the moment a
rescued citizen stands near the temple with a rishi alive — i.e. exactly when the Shishya/soldier
mechanic is supposed to start. The throw happens inside `saintsTick → soldierTick → update`, so the
rest of `update()` is skipped after that point: `updateHud()` is never reached, `if(hero.hp<=0)finish()`
is never reached, waves/pickups/camera stop advancing. The outer `loop()` swallows it with
`catch(err){console.error(err)}`, so the player just sees a frozen, non-updating game.

```
ReferenceError: gv is not defined
    at soldierTick (…:781:88)
    at saintsTick (…:795:25)
    at update (…:508:15)
```

`gv` also threw a second time from the menu path. **Fix applied:** dropped the multiplier (`.4)`).

## 6 — High: implicit global in `"use strict"` code

```js
// draw(), line 903 (inside the main IIFE which starts with 'use strict')
{_sc=zScale(hero.y);c.fillStyle='#00000030';…}
```

`_sc` is never declared (`let _sw=0,_l1=0,_l2=0,_atk=0,_ph=0,_mvv=0` nearby, but no `_sc`).
Assignment to an undeclared identifier throws `ReferenceError` in strict mode, so the whole hero
rendering block after it (hero figure, staff/bow, aura) never draws.

```
$ node -e "(()=>{'use strict'; {_sc=5}})" → ReferenceError: _sc is not defined
```

**Fix applied:** `{const _sc=zScale(hero.y); …}`.

> Note: the jsdom build used for the harness does *not* throw here (its strict-mode evaluation quirk),
> so this was confirmed with `node`/`vm` rather than in the browser harness. It is a real engine-level
> ReferenceError in Chrome/Safari/Firefox.

## 7 — High: `mf2` is out of scope (the procedural mantra singer is dead code)

```js
const SINGER={};
(function(){
  const SA2=130.81,mf2=s=>SA2*Math.pow(2,s/12);   // block scope
  SINGER.profile={…};
})();
…
function synthesizeMantra(mantraKey, profile){
  const baseFreq=mf2(profile.base);      // ReferenceError
  const freq=mf2(profile.base+step);     // ReferenceError
}
```

`mf2` only ever exists inside the IIFE. Every path that reaches the synthesized Sanskrit chant
(`playMantra → renderFullMantra → synthesizeMantra`) throws `ReferenceError: mf2 is not defined`,
and `beginRitual()` wraps the call in the *audio* `try` block only, so the ritual UI still shows but
the chant never renders. ESLint flags it (2× `no-undef`).

**Fix applied:** hoisted the helper onto the object — `SINGER.mf2=s=>130.81*Math.pow(2,s/12);` — and
updated the two call sites.

## 8 — Medium: mantra ritual ends immediately (wrong unit)

```js
ritual.se=buf.duration/A.ctx.sampleRate+1;   // line 490
```

`buf.duration` is already in **seconds**; dividing by `44100` yields `≈0.00008`. `ritual.se` is the
"expected end time" used both for the progress bar and for the auto-close condition
`R.t>=5.4 && R.td && R.t>=R.se`, so the mantra screen closes after the first frame instead of after
the chant.

```
ritual.se = 3.5/44100 + 1 = 1.000079  (should be ≈ 4.5)
```

The sibling code paths are all in seconds (`ritual.se=5.4`, `ritual.se=b.duration+.4`), confirming the
intent. **Fix applied:** `ritual.se=buf.duration+1;`.

## 9 — Medium: inline `onclick` handlers can't see the functions

```html
<div class="diff-chip" data-d="hard" onclick="previewDiff('hard')">HARD</div>   <!-- OK, exported -->
<button id="endHowBtn" onclick="openHow()">GUIDE</button>
<button onclick="setDiff('hard')">HARD</button>
<button onclick="$('diffMenu').style.display='none'">CANCEL</button>
```

`openHow`, `closeHow`, `setDiff`, `openDiff` and `$` all live inside the `(()=>{…})()` IIFE, so inline
handlers evaluate them in global scope:

```
ReferenceError: openHow is not defined
    at HTMLButtonElement.onclick (…:6:1)
```

Concretely: the **GUIDE** button on the game-over screen and the three difficulty buttons in the
**SELECT DIFFICULTY** overlay were dead (the overlay could not even be cancelled without the keyboard).
**Fix applied:** explicit exports next to `window.previewDiff`:

```js
window.openHow=openHow;window.closeHow=closeHow;window.setDiff=setDiff;window.openDiff=openDiff;window.$=$;
```

Verified: `inline setDiff(hard)` → `{"badge":"HARD MODE","obj":"[HARD] TEMPLE 100% · RISHIS 3 …"}`,
and `endHowBtn` now opens the guide with 0 console errors.

---

## Verified working after the fixes

Harness runs (jsdom, stubbed canvas + WebAudio, thousands of frames):

* boot → menu (weapon strip 7 items) → START → HUD → 600 frames with movement + firing: **0 errors**
* all 9 "How to play" tabs render; guided-coach buttons wired
* all **12 deities**: invoke → ritual → manifest → expire (`shield, chakra, durga, hanuman, surya,
  indra, kartikeya, narasimha, ganesha, kali, rama, lakshmi`)
* all **7 astras** fire (`AGNI, VARUNA, VAYU, VAJRA, BRAHMA, NAGA, NARAYAN`)
* all **8 bosses** in order + wrap-around (TATAKA → RAVANA → TATAKA), unlock progression
  (`bk/ck` → all 7 astras unlocked) and `localStorage` persistence
* boons: every rarity tier offered, stacking to max, 26 level-ups in one run without a NaN in
  `hero.power/rate/speed/hp` or shot damage
* ultimate (12 allies), pause/resume, auto-aim/music/haptics toggles, player death → end screen →
  restart, temple destruction → end screen

## Remaining / low-priority observations

1. **`#mSkip` ("TAP TO CONTINUE") has no listener.** Skipping works because `#mantra` itself has a
   `pointerdown` handler that sets `ritual.skip` after 2.5 s — but the element that *looks* tappable
   does nothing, which is confusing. Cheap fix: `$('mSkip').onclick=()=>{if(ritual)ritual.skip=true}`.
2. **Overlay stacking:** `divineCall()` is only guarded by `paused`, so it can be triggered while the
   boon screen (`#upgrade`) is open, stacking `#codex` over it. `togglePause()` correctly early-returns;
   the other overlay openers (`divineCall`, `openHow`, `openDiff`) could use the same guard.
3. **Audio-only chants:** only four mantras exist as embedded audio (`shield, chakra, durga, hanuman`);
   the other eight fall back to the procedural singer (fixed in #7) or `speechSynthesis`.
4. `loadAud()` declares `let pr=x.decodeAudioData(...)` then calls `pr&&pr.catch(...)` — `decodeAudioData`
   historically returns `undefined` in some browsers; the guard makes it harmless, but the callback
   style used (`(buffer, onError)`) is deprecated in favour of a promise.
5. `stage` `#diffBadge`/`#battleLog` were designed `position:fixed`; after the markup fix they sit
   directly under `#hud` in the body, which is what the CSS expects.
