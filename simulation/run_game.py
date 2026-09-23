#!/usr/bin/env python3
"""Entry point. Run from anywhere:

    python3 simulation/run_game.py                  # mouse controls mallet 0, panel on the right
    python3 simulation/run_game.py --scripted       # mallet 0 chases the puck, no mouse needed
    python3 simulation/run_game.py --ascii          # no window, ASCII frames in the terminal
    python3 simulation/run_game.py --scripted --headless --seconds 4
    python3 simulation/run_game.py --params my.json    # use a different parameter file
    python3 simulation/run_game.py --no-panel           # clean window, no sliders

Controls
    mouse            mallet 0 follows the cursor, as a force, so it accelerates and brakes
    drag a slider    set that parameter, live, and watch the effect immediately
    Save button or S save the current values to the parameter file
    Reload button or R   reload the file from disk
    Defaults button or D restore the defaults in memory, not saved until you press S
    P                show or hide the panel
    Space            serve a fresh puck
    Escape or close the window to stop

While the pointer is over the panel the mallet gets no force, so dragging a slider does not
also fling the mallet across the table. A summary prints on exit.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import view                                                    # noqa: E402
from input import ForceController, MouseInput, ScriptedInput    # noqa: E402
from panel import ParamPanel                                    # noqa: E402
from params import DEFAULT_PARAMS_PATH, Params                  # noqa: E402
from world import EVENT_GOAL_FAR, EVENT_GOAL_NEAR, World        # noqa: E402

WINDOW_W, WINDOW_H = 1180, 660
PANEL_W = 330.0
PANEL_MARGIN = 10.0


def panel_rect(window_w: int, window_h: int) -> tuple[float, float, float, float]:
    return (window_w - PANEL_W - PANEL_MARGIN, PANEL_MARGIN,
            PANEL_W, window_h - 2 * PANEL_MARGIN)


def table_rect(window_w: int, window_h: int, panel_on: bool) -> tuple[float, float, float, float]:
    return (0.0, 0.0, (window_w - PANEL_W - 2 * PANEL_MARGIN) if panel_on else window_w,
            float(window_h))


def serve(world: World, speed: float) -> None:
    """Put the puck in play, travelling toward the driven mallet at the near end."""
    arena = world.arena
    x0, y0 = arena.length_m * 0.85, arena.centre_y
    dx, dy = 0.0 - x0, arena.centre_y - y0
    norm = max(1e-9, (dx * dx + dy * dy) ** 0.5)
    world.puck.launch(x0, y0, speed * dx / norm, speed * dy / norm)


def run(args) -> int:
    import pygame

    if args.headless or args.save:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    screen = None if args.ascii else pygame.display.set_mode((WINDOW_W, WINDOW_H))
    if screen is not None:
        pygame.display.set_caption("Air hockey simulator")

    params = Params.load(args.params)
    if params.path:
        params.path = args.params

    world = World()
    world.reset_placement()
    controller = ForceController(mallet_index=0)
    params.apply(world, controller)
    serve(world, params.get("serve_speed_m_s"))

    panel_on = not args.no_panel
    panel = ParamPanel(params, panel_rect(WINDOW_W, WINDOW_H))
    if params.dirty:
        panel.note("loaded, defaults for missing keys")
    else:
        panel.note(f"loaded {os.path.basename(params.path)}" if os.path.exists(params.path)
                   else "defaults (no parameter file yet)")

    if args.scripted:
        source = ScriptedInput(target_m=(world.mallets[0].x, world.mallets[0].y),
                               controller=controller)
    else:
        source = MouseInput(view.Layout.fit_in_rect(world.arena, table_rect(WINDOW_W, WINDOW_H,
                                                                           panel_on)),
                            controller=controller)

    recorder = view.GifRecorder(every=args.gif_every) if args.save else None
    clock = pygame.time.Clock()
    layout = view.Layout.fit_in_rect(world.arena, table_rect(WINDOW_W, WINDOW_H, panel_on))
    accum = 0.0
    elapsed = 0.0
    goals_near = goals_far = 0
    peak_mallet = peak_belt = 0.0
    pointer_over_panel = False
    frame = 0
    ascii_every = max(1, int(args.fps * 0.25))
    running = True

    while running:
        real_dt = clock.tick(args.fps) / 1000.0
        accum += min(real_dt, 0.05) * params.get("time_scale")

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_p:
                    panel_on = not panel_on
                    layout = view.Layout.fit_in_rect(
                        world.arena, table_rect(WINDOW_W, WINDOW_H, panel_on))
                    if isinstance(source, MouseInput):
                        source.layout = layout
                elif event.key == pygame.K_s:
                    panel.save()
                elif event.key == pygame.K_r:
                    panel.reload()
                elif event.key == pygame.K_d:
                    panel.defaults()
                elif event.key == pygame.K_SPACE:
                    world.reset_placement(reset_clock=False)
                    serve(world, params.get("serve_speed_m_s"))
            elif panel_on and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                panel.pointer_down(*event.pos)
            elif panel_on and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                panel.pointer_up()
            elif panel_on and event.type == pygame.MOUSEMOTION:
                if panel.dragging is not None:
                    panel.pointer_drag(*event.pos)

        # layer 2: turn the cursor into a force on mallet 0, unless the panel has the pointer
        pointer = pygame.mouse.get_pos()
        pointer_over_panel = panel_on and panel.contains(*pointer)
        if args.scripted:
            source.aim_at_puck(world)
            source.apply(world)
        elif panel.dragging is not None or pointer_over_panel:
            world.set_force(0, 0.0, 0.0)          # editing, so let the mallet coast
        else:
            source.update_pointer(pointer if screen is not None else (WINDOW_W / 2, WINDOW_H / 2))
            source.apply(world)

        params.apply(world, controller)           # every frame, so the sliders are live

        while accum >= world.dt_s and running:
            world.step(world.dt_s)
            accum -= world.dt_s
            elapsed += world.dt_s
            peak_mallet = max(peak_mallet, world.mallets[0].speed)
            peak_belt = max(peak_belt, max(world.mallets[0].belt_speeds))
            if world.event in (EVENT_GOAL_NEAR, EVENT_GOAL_FAR):
                if world.event == EVENT_GOAL_NEAR:
                    goals_near += 1
                else:
                    goals_far += 1
                world.reset_placement(reset_clock=False)
                serve(world, params.get("serve_speed_m_s"))
            if args.seconds and elapsed >= args.seconds:
                running = False

        if screen is not None:
            frame += 1
            hud = view.hud_lines(world, layout)
            hud.append(f"time scale {params.get('time_scale'):.2f}x   "
                       f"serve {params.get('serve_speed_m_s'):.2f} m/s")
            if pointer_over_panel or panel.dragging is not None:
                hud.append("pointer on panel: mallet idle")
            view.draw_scene(screen, world, layout, hud,
                            target_m=getattr(source, "target_m", None))
            if panel_on:
                panel.draw(screen)
            pygame.display.flip()
            if recorder:
                recorder.maybe_capture(screen)
        elif args.ascii and frame % ascii_every == 0:
            print(view.ascii_frame(world))
            print()
            frame = 1
        else:
            frame += 1

    if recorder:
        print(f"gif written to {recorder.save(args.save, fps=args.gif_fps)} "
              f"({len(recorder.frames)} frames)")
    print(f"ran {elapsed:.2f} s of simulated time in {world.n_steps} steps at "
          f"{1.0 / world.dt_s:.0f} Hz")
    print(f"goals: {goals_near} against mallet 0, {goals_far} for mallet 0")
    print(f"peak mallet 0 speed {peak_mallet:.2f} m/s "
          f"(axial limit {world.mallets[0].axial_speed_limit_m_s:.1f}, "
          f"diagonal limit {world.mallets[0].diagonal_speed_limit_m_s:.2f})")
    print(f"peak belt speed {peak_belt:.2f} m/s")
    print(f"peak puck speed {world.max_puck_speed:.2f} m/s")
    if params.dirty:
        print(f"parameters have unsaved changes. press S or use the Save button "
              f"(file: {params.path})")
    else:
        print(f"parameters: {params.path}")
    if screen is not None:
        pygame.quit()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="air hockey simulator, two layers")
    ap.add_argument("--scripted", action="store_true",
                    help="mallet 0 chases the puck instead of the mouse")
    ap.add_argument("--ascii", action="store_true", help="no window, print ASCII frames")
    ap.add_argument("--headless", action="store_true", help="no window, no ASCII")
    ap.add_argument("--no-panel", action="store_true", help="hide the parameter panel")
    ap.add_argument("--params", default=DEFAULT_PARAMS_PATH,
                    help="parameter file to load, and to save to")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="stop after this much simulated time. 0 means until you quit")
    ap.add_argument("--fps", type=int, default=60, help="render and input rate")
    ap.add_argument("--save", default=None, help="record a gif to this path")
    ap.add_argument("--gif-fps", type=int, default=25)
    ap.add_argument("--gif-every", type=int, default=2, help="capture every Nth frame")
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
