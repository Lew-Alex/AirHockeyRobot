# Air hockey simulator

Two layers.

**Layer 1 is the world.** An arena 24 x 48 inches, one puck that carries all of its own
physics, and two mallets. A mallet is driven by a force in a direction and nothing else.
With no force it does not move, so the second mallet just sits there. The mallet's speed
limit is per belt: 10 m/s, which gives 10 m/s along an axis and 7.07 m/s on a diagonal,
because a CoreXY drives both belts at once on a diagonal.

**Layer 2 is the inputs.** Right now one mallet is driven, and only by the mouse. The
cursor is a target, a force pulls the mallet toward it, and the force is capped and damped
so the mallet arrives rather than oscillating. Mallet 1 has no input at all.

## Run it

```
python3 simulation/run_game.py                 # mouse controls mallet 0, in a window
python3 simulation/run_game.py --ascii         # no window, ASCII frames in the terminal
python3 simulation/run_game.py --scripted      # mallet 0 chases the puck instead of the mouse
python3 simulation/run_game.py --scripted --headless --seconds 4    # a timed headless run
python3 simulation/run_game.py --scripted --save /tmp/rally.gif     # record a gif
python3 simulation/run_tests.py                # 64 unit tests
```

Controls: move the mouse and mallet 0 follows it. Escape or close the window to stop. A
summary of peak speeds, goals and limits prints on exit.

Dependencies: numpy, pygame (window and gif), Pillow (gif only).

## Layout

| File | Layer | What it owns |
|---|---|---|
| `arena.py` | 1 | the 24 x 48 in rectangle, the goal mouths, wall bounces, inch to metre conversion |
| `puck.py` | 1 | the puck's own physics: drag, wall response, and the mallet collision |
| `mallet.py` | 1 | force input, the driven mass, and the per-belt speed limit |
| `world.py` | 1 | arena plus puck plus two mallets, on a fixed 1 ms step |
| `kinematics.py` | 1 | CoreXY mapping, which is where the diagonal limit comes from |
| `input.py` | 2 | target point to force, and mouse pixels to a target point |
| `params.py` | - | the tunable values, their ranges, and the save and load |
| `panel.py` | - | the sliders and buttons, hit-tested with plain arithmetic |
| `view.py` | - | pixel layout, pygame drawing, ASCII frame, gif recorder |
| `run_game.py` | - | the loop that joins the two layers and the view |
| `tests/` | - | one test file per module |

## Tunable parameters, in the window

The panel on the right of the window drives every number the model depends on. Drag a
slider and the change is live, so you can watch a puck glide forever on zero drag and die
halfway across on a sliding friction of 0.1.

| Group | Parameter | Range | Default |
|---|---|---|---|
| puck | mass | 0.005 to 0.060 kg | 0.022 |
| puck | radius | 0.015 to 0.045 m | 0.03175 |
| puck | linear drag | 0 to 1.0 /s | 0.08 |
| puck | sliding friction (Coulomb mu) | 0 to 0.20 | 0.002 |
| mallet | driven mass | 0.05 to 3.0 kg | 0.60 |
| mallet | restitution e | 0 to 1.0 | 0.70 |
| mallet | radius | 0.02 to 0.06 m | 0.04125 |
| mallet | belt speed limit | 1 to 20 m/s | 10.0 |
| arena | wall restitution | 0 to 1.0 | 0.90 |
| arena | goal width | 3 to 24 in | 12.0 |
| input | pointer stiffness | 20 to 2000 N/m | 400 |
| input | pointer damping | 0 to 200 Ns/m | 40 |
| input | force ceiling | 20 to 2000 N | 400 |
| run | time scale | 0.05 to 2.0x | 1.0 |
| run | serve speed | 0 to 15 m/s | 1.0 |

* **Save** or `S` writes the file, default `simulation/params.json`, and `--params other.json`
  uses a different one. The file is plain JSON with a `values` object, so it can be edited by
  hand or checked into the repo as a preset.
* **Reload** or `R` re-reads the file, which is how an external edit lands.
* **Defaults** or `D` restores the defaults in memory. Nothing is written until you save.
* A parameter that differs from its default is shown in red, and the panel says
  "unsaved changes" until you save.
* Values are clamped to their range on the way in, from the slider or from the file, so a
  hand-edited file cannot push the model somewhere it cannot represent.
* While the pointer is over the panel the mallet gets no force, so dragging a slider does
  not also fling it across the table.

Layer 1 never learns about the panel: `params.apply(world, controller)` is the only writer,
and it runs once per frame so the sliders are live.

### Units of the two drag terms

Both are **decelerations, not forces**, so neither is in newtons:

```
deceleration [m/s2] = drag_per_s * speed  +  coulomb_mu * g
```

* `drag_per_s` is therefore in **1/s**. It is the speed at which the glide decays: with
  0.08 the linear part has a 12.5 s time constant, which is why a puck crosses the table
  with only a few percent lost.
* `coulomb_mu` is **dimensionless**, a friction coefficient. `mu * g` is a constant
  deceleration and does not depend on the puck's mass, which is standard for sliding
  friction.

To think in newtons, multiply the deceleration by the puck mass. Defaults, 22 g puck:

| Puck speed | Deceleration | Force | of which linear | of which friction |
|---|---|---|---|---|
| 0.5 m/s | 0.060 m/s2 | 1.31 mN | 0.88 mN | 0.43 mN |
| 1 m/s | 0.100 m/s2 | 2.19 mN | 1.76 mN | 0.43 mN |
| 5 m/s | 0.420 m/s2 | 9.23 mN | 8.80 mN | 0.43 mN |
| 10 m/s | 0.820 m/s2 | 18.0 mN | 17.6 mN | 0.43 mN |

The equivalent viscous coefficient is `c = drag_per_s * mass`, so the defaults are
0.00176 N s/m. If you would rather set `c` directly in N s/m, the trade is that the glide
then changes with the puck mass slider, which is physically more honest but harder to dial
by feel. Say the word and it is a one line change.

## The two layers, concretely

Layer 1 accepts exactly one kind of input:

```python
world.set_force(0, fx, fy)     # newtons on mallet 0. Nothing else reaches layer 1
world.step()                   # one millisecond
```

Layer 2 turns a mouse position into that force:

```python
mouse.update_pointer(pygame.mouse.get_pos())   # pixels
mouse.apply(world)                             # arena target, then a force
```

The chain in full: mouse pixels, arena metres, a damped spring force toward that point,
mallet acceleration over the driven mass, belt speed clipping, position.

## Numbers in the model

| Quantity | Value | Where it comes from |
|---|---|---|
| Arena | 48 x 24 in (1.2192 x 0.6096 m) | as specified |
| Goal mouth | 12 in | estimate, measure the real table |
| Mallet speed limit | 10 m/s per belt, so 7.07 m/s diagonal | as specified |
| Mallet radius | 41.25 mm (3.25 in) | to be measured |
| Driven mass | 0.60 kg | mallet plus its share of the carriage, from the sizing study |
| Mallet restitution | 0.70 | project note. Range 0.6 to 0.9 |
| Puck | 22 g, 31.75 mm radius | to be weighed |
| Puck drag | 0.08 /s linear, 0.002 Coulomb | estimate. About 1.3 percent over 2 m |
| Wall restitution | 0.90 | estimate |
| Timestep | 1 ms | matches the eventual control loop rate |

The mallet has no rail friction, so a released mallet coasts. That is deliberate: layer 1
has one acceleration model and no hidden damping, and layer 2's damping term is what stops
the mallet. If you want the mallet to coast to a halt on its own, that is a term in
`Mallet.apply_force`.

## Verified

64 tests, all passing, and these behaviours are asserted rather than hoped for:

* a pure-axis push reaches exactly 10 m/s and a 45 degree push exactly 7.07, with the belt
  cap respected at every angle from 0 to 90 degrees
* the undriven mallet never moves, even while mallet 0 is driven across the table
* a mallet cannot be pushed off the table, at any force
* the puck's contact with a mallet matches the closed-form collision model exactly
* the tangential velocity component survives a contact while the normal component reverses
* a puck travelling 360 mm inside a single 12 ms step, ending 334 mm past the mallet, is
  still caught (the swept contact, not a discrete overlap test)
* a 48 inch table crosses in length over speed, within 60 ms
* a forced goal at either end is reported, and the mallets' goal lines are where they claim
* the whole thing replays identically from the same seed

## Fixed while building this

* A goal used to call a reset that zeroed the world clock, so a game loop that stops on
  "t >= seconds" would never stop. `reset_placement(reset_clock=False)` keeps the timeline
  running across goals.
* The goalie-style chase policy and the mouse map through the same `ForceController`, so
  everything a headless test exercises is the code path the mouse uses.
* With the arena's y flipped so the near goal is at the bottom of the screen, the cursor
  round-trips through `Layout` exactly, which is what makes the mouse feel right.

## Next

* Mallet 1 is waiting for a second input. It already accepts a force, so it is an input
  binding away.
* The goal mouths are guesses. Measure the table.
* Anything that needs the puck to be hit correctly at speed should wait for the real motor
  model, which replaces `Mallet.apply_force` with a torque-speed curve once milestone 4
  verifies the current limit.
