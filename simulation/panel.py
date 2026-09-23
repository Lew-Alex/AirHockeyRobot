"""The parameter panel: sliders in the window for the tunable values, plus save and reload.

Geometry is plain numbers and the hit tests are plain arithmetic, so the panel can be
driven and tested with no display. Only `draw` touches pygame.

Interaction, deliberately the simplest thing that works:

  * click or drag anywhere on a slider row to set that value, proportional to where you
    clicked, so you do not have to grab a small knob
  * the three buttons at the bottom save, reload from disk, or go back to the defaults
  * while the pointer is over the panel the mallet gets no force, so dragging a slider
    does not also fling the mallet across the table
"""
from __future__ import annotations

from params import GROUPS, SCHEMA, Param, Params

HEADER_H = 20.0
ROW_H = 22.0
BUTTON_H = 28.0
PAD = 10.0
LABEL_W = 150.0
VALUE_W = 74.0

COLOUR_PANEL = (250, 250, 250)
COLOUR_BORDER = (150, 150, 150)
COLOUR_HEADER = (90, 90, 120)
COLOUR_LABEL = (40, 40, 40)
COLOUR_VALUE = (20, 20, 20)
COLOUR_TRACK = (210, 210, 210)
COLOUR_FILL = (170, 200, 230)
COLOUR_KNOB = (60, 110, 170)
COLOUR_EDITED = (200, 60, 40)
COLOUR_BUTTON = (238, 238, 238)

BUTTONS = ("save", "reload", "defaults")
BUTTON_LABELS = {"save": "Save", "reload": "Reload", "defaults": "Defaults"}


def hit(rect: tuple[float, float, float, float], px: float, py: float) -> bool:
    x, y, w, h = rect
    return x <= px <= x + w and y <= py <= y + h


class Slider:
    """One parameter, one row."""

    def __init__(self, param: Param, rect: tuple[float, float, float, float]):
        self.param = param
        self.rect = rect

    @property
    def track(self) -> tuple[float, float, float]:
        x, y, w, h = self.rect
        x0 = x + LABEL_W
        x1 = x + w - VALUE_W
        return x0, x1 - x0, y + h / 2.0

    def value_from_pointer(self, px: float) -> float:
        x0, width, _ = self.track
        frac = 0.0 if width <= 0 else (px - x0) / width
        frac = min(max(frac, 0.0), 1.0)
        return self.param.clamp(self.param.minimum + frac * (self.param.maximum - self.param.minimum))

    def knob_x(self, value: float) -> float:
        x0, width, _ = self.track
        span = self.param.maximum - self.param.minimum
        frac = 0.0 if span <= 0 else (value - self.param.minimum) / span
        return x0 + min(max(frac, 0.0), 1.0) * width


class ParamPanel:
    """The whole panel: headers, a slider per parameter, three buttons."""

    def __init__(self, params: Params, rect: tuple[float, float, float, float]):
        self.params = params
        self.rect = rect
        self.rows: list[tuple[str, object, tuple[float, float, float, float]]] = []
        self.messages: list[str] = []
        self.dragging: Slider | None = None
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self) -> None:
        x, y, w, _ = self.rect
        cursor = y + PAD
        group = None
        for param in SCHEMA:
            if param.group != group:
                group = param.group
                self.rows.append(("header", group, (x + PAD, cursor, w - 2 * PAD, HEADER_H)))
                cursor += HEADER_H
            self.rows.append(("slider", Slider(param, (x + PAD, cursor, w - 2 * PAD, ROW_H)),
                              (x + PAD, cursor, w - 2 * PAD, ROW_H)))
            cursor += ROW_H
        cursor += PAD
        button_w = (w - 2 * PAD - 2 * 6.0) / 3.0
        for i, name in enumerate(BUTTONS):
            bx = x + PAD + i * (button_w + 6.0)
            self.rows.append(("button", name, (bx, cursor, button_w, BUTTON_H)))

    @property
    def sliders(self) -> list[Slider]:
        return [row[1] for row in self.rows
                if row[0] == "slider" and isinstance(row[1], Slider)]

    def slider_for(self, key: str) -> Slider:
        for slider in self.sliders:
            if slider.param.key == key:
                return slider
        raise KeyError(key)

    # ------------------------------------------------------------------ input
    def contains(self, px: float, py: float) -> bool:
        return hit(self.rect, px, py)

    def pointer_down(self, px: float, py: float) -> str | None:
        """Returns what was grabbed: 'slider:<key>', 'button:<name>', or None."""
        if not self.contains(px, py):
            return None
        for kind, payload, rect in self.rows:
            if not hit(rect, px, py):
                continue
            if kind == "slider" and isinstance(payload, Slider):
                self.dragging = payload
                self.params.set(payload.param.key, payload.value_from_pointer(px))
                return f"slider:{payload.param.key}"
            if kind == "button" and isinstance(payload, str):
                return self.activate_button(payload)
        return "panel"

    def pointer_drag(self, px: float, py: float) -> None:
        if self.dragging is not None:
            self.params.set(self.dragging.param.key, self.dragging.value_from_pointer(px))

    def pointer_up(self) -> None:
        self.dragging = None

    def click(self, px: float, py: float) -> str | None:
        """A complete click, for tests and for code that does not track drag state."""
        grabbed = self.pointer_down(px, py)
        self.pointer_up()
        return grabbed

    def activate_button(self, name: str) -> str:
        self.pointer_up()
        if name == "save":
            return self.save()
        if name == "reload":
            return self.reload()
        if name == "defaults":
            return self.defaults()
        raise KeyError(name)

    # ------------------------------------------------------------------ actions
    def note(self, message: str) -> None:
        self.messages.append(message)
        del self.messages[:-4]

    @property
    def message(self) -> str:
        return self.messages[-1] if self.messages else ""

    def save(self) -> str:
        path = self.params.save()
        self.note(f"saved to {path}")
        return "saved"

    def reload(self) -> str:
        self.params.reload()
        self.note("reloaded from disk")
        return "reloaded"

    def defaults(self) -> str:
        self.params.reset_to_defaults()
        self.note("defaults restored, not yet saved")
        return "defaults"

    # ------------------------------------------------------------------ drawing
    def draw(self, screen, arena=None) -> None:
        import pygame

        x, y, w, h = self.rect
        pygame.draw.rect(screen, COLOUR_PANEL, pygame.Rect(int(x), int(y), int(w), int(h)))
        pygame.draw.rect(screen, COLOUR_BORDER, pygame.Rect(int(x), int(y), int(w), int(h)), 1)
        font = pygame.font.SysFont(None, 18)
        small = pygame.font.SysFont(None, 15)

        for kind, payload, rect in self.rows:
            rx, ry, rw, rh = rect
            if kind == "header":
                label = str(payload).upper()
                screen.blit(small.render(label, True, COLOUR_HEADER), (int(rx), int(ry + 4)))
                pygame.draw.line(screen, COLOUR_TRACK, (rx, ry + rh - 2), (rx + rw, ry + rh - 2), 1)
            elif kind == "slider" and isinstance(payload, Slider):
                slider = payload
                param = slider.param
                value = self.params.get(param.key)
                edited = abs(value - param.default) > 1e-9
                screen.blit(font.render(param.label, True, COLOUR_LABEL), (int(rx), int(ry + 3)))
                x0, tw, ty = slider.track
                pygame.draw.line(screen, COLOUR_TRACK, (x0, ty), (x0 + tw, ty), 3)
                kx = slider.knob_x(value)
                pygame.draw.line(screen, COLOUR_FILL, (x0, ty), (kx, ty), 3)
                pygame.draw.circle(screen, COLOUR_KNOB, (int(kx), int(ty)), 5)
                text = param.format(value)
                colour = COLOUR_EDITED if edited else COLOUR_VALUE
                screen.blit(font.render(text, True, colour), (int(rx + rw - VALUE_W + 4), int(ry + 3)))
            else:
                name = str(payload)
                pygame.draw.rect(screen, COLOUR_BUTTON, pygame.Rect(int(rx), int(ry), int(rw), int(rh)))
                pygame.draw.rect(screen, COLOUR_BORDER, pygame.Rect(int(rx), int(ry), int(rw), int(rh)), 1)
                text = BUTTON_LABELS.get(name, name)
                size = font.size(text)
                screen.blit(font.render(text, True, COLOUR_LABEL),
                            (int(rx + (rw - size[0]) / 2), int(ry + (rh - size[1]) / 2)))

        if self.params.dirty:
            screen.blit(small.render("unsaved changes", True, COLOUR_EDITED),
                        (int(x + PAD), int(y + 4)))
        if self.message:
            screen.blit(small.render(self.message, True, COLOUR_HEADER),
                        (int(x + PAD), int(y + h - 14)))
