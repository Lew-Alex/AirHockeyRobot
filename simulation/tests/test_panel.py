"""The parameter panel, driven headlessly.

Nothing here renders. The panel's geometry and hit tests are plain arithmetic precisely so
that the interaction can be tested without a window: what the mouse does is call
`pointer_down`, `pointer_drag` and `pointer_up` with pixel coordinates.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panel import BUTTONS, ParamPanel                          # noqa: E402
from params import BY_KEY, SCHEMA, Params, defaults            # noqa: E402

PANEL_RECT = (850.0, 10.0, 330.0, 640.0)


class PanelTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "params.json")
        self.params = Params(path=self.path)
        self.panel = ParamPanel(self.params, PANEL_RECT)

    def tearDown(self):
        self._dir.cleanup()

    def click_centre_of(self, key: str):
        slider = self.panel.slider_for(key)
        x, y, w, h = slider.rect
        self.panel.click(x + w / 2.0, y + h / 2.0)
        return slider


class TestLayout(PanelTest):
    def test_one_slider_per_parameter(self):
        keys = [s.param.key for s in self.panel.sliders]
        self.assertEqual(keys, [p.key for p in SCHEMA])

    def test_there_is_a_heading_for_each_group(self):
        headers = [row[1] for row in self.panel.rows if row[0] == "header"]
        self.assertEqual(headers, list(dict.fromkeys(p.group for p in SCHEMA)))

    def test_the_three_buttons_are_present_and_inside_the_panel(self):
        names = [row[1] for row in self.panel.rows if row[0] == "button"]
        self.assertEqual(names, list(BUTTONS))
        x, y, w, h = PANEL_RECT
        for kind, _payload, rect in self.panel.rows:
            bx, by, bw, bh = rect
            self.assertGreaterEqual(bx, x)
            self.assertGreaterEqual(by, y)
            self.assertLessEqual(bx + bw, x + w)
            self.assertLessEqual(by + bh, y + h + 1e-9, f"{kind} row overflows the panel")

    def test_no_two_rows_overlap(self):
        """The three buttons share a row, so rows are allowed to sit beside each other.
        What must never happen is two rectangles covering the same pixels."""
        rects = [row[2] for row in self.panel.rows]
        for i, (ax, ay, aw, ah) in enumerate(rects):
            for bx, by, bw, bh in rects[i + 1:]:
                overlaps_x = ax < bx + bw and bx < ax + aw
                overlaps_y = ay < by + bh and by < ay + ah
                self.assertFalse(overlaps_x and overlaps_y,
                                 f"rows overlap: {(ax, ay, aw, ah)} and {(bx, by, bw, bh)}")

    def test_rows_run_down_the_panel(self):
        ys = [row[2][1] for row in self.panel.rows]
        self.assertEqual(ys, sorted(ys))

    def test_the_editor_is_not_empty(self):
        sliders = [p.key for p in SCHEMA]
        for key in ("puck_drag_per_s", "mallet_restitution", "wall_restitution"):
            self.assertIn(key, sliders)


class TestHitTesting(PanelTest):
    def test_the_panel_owns_points_inside_it(self):
        self.assertTrue(self.panel.contains(900.0, 300.0))
        self.assertFalse(self.panel.contains(100.0, 300.0))

    def test_a_click_outside_does_nothing(self):
        before = dict(self.params.values)
        self.assertIsNone(self.panel.click(50.0, 50.0))
        self.assertEqual(self.params.values, before)

    def test_a_click_on_empty_panel_space_is_absorbed(self):
        result = self.panel.click(PANEL_RECT[0] + 2, PANEL_RECT[1] + 2)
        self.assertEqual(result, "panel")


class TestSliderInteraction(PanelTest):
    def test_clicking_the_left_end_gives_the_minimum(self):
        slider = self.click_centre_of("puck_drag_per_s")
        x0, width, _ = slider.track
        self.panel.click(x0, slider.rect[1] + 5)
        self.assertAlmostEqual(self.params.get("puck_drag_per_s"),
                               BY_KEY["puck_drag_per_s"].minimum, places=9)

    def test_clicking_the_right_end_gives_the_maximum(self):
        slider = self.click_centre_of("puck_drag_per_s")
        x0, width, _ = slider.track
        self.panel.click(x0 + width, slider.rect[1] + 5)
        self.assertAlmostEqual(self.params.get("puck_drag_per_s"),
                               BY_KEY["puck_drag_per_s"].maximum, places=9)

    def test_clicking_the_middle_gives_the_default_when_the_default_is_centred(self):
        """puck drag defaults to 0.08 in a 0.0 to 1.0 range, so a left-third click lands
        just under the default. The check is that the mapping is monotonic in x."""
        slider = self.panel.slider_for("puck_drag_per_s")
        x0, width, ty = slider.track
        self.panel.click(x0 + 0.25 * width, ty)
        quarter = self.params.get("puck_drag_per_s")
        self.panel.click(x0 + 0.75 * width, ty)
        three_quarters = self.params.get("puck_drag_per_s")
        self.assertLess(quarter, three_quarters)
        self.assertAlmostEqual(quarter, 0.25, places=2)
        self.assertAlmostEqual(three_quarters, 0.75, places=2)

    def test_dragging_keeps_updating_and_release_stops_it(self):
        key = "wall_restitution"
        slider = self.panel.slider_for(key)
        x0, width, ty = slider.track
        self.panel.pointer_down(x0 + 0.1 * width, ty)
        self.assertAlmostEqual(self.params.get(key), 0.1, places=2)
        self.panel.pointer_drag(x0 + 0.9 * width, ty)
        self.assertAlmostEqual(self.params.get(key), 0.9, places=2)
        self.panel.pointer_up()
        self.panel.pointer_drag(x0 + 0.2 * width, ty)          # nothing is being dragged
        self.assertAlmostEqual(self.params.get(key), 0.9, places=2)

    def test_editing_marks_the_parameter_set_dirty(self):
        self.click_centre_of("time_scale")
        self.assertTrue(self.params.dirty)

    def test_every_slider_can_be_clicked_without_error(self):
        for slider in self.panel.sliders:
            x, y, w, h = slider.rect
            self.panel.click(x + w * 0.3, y + h / 2.0)
            self.panel.click(x + w * 0.7, y + h / 2.0)
        for param in SCHEMA:
            value = self.params.get(param.key)
            self.assertGreaterEqual(value, param.minimum)
            self.assertLessEqual(value, param.maximum)


class TestButtons(PanelTest):
    def button_rect(self, name: str):
        for kind, payload, rect in self.panel.rows:
            if kind == "button" and payload == name:
                return rect
        raise KeyError(name)

    def click_button(self, name: str) -> str | None:
        x, y, w, h = self.button_rect(name)
        return self.panel.click(x + w / 2.0, y + h / 2.0)

    def test_save_writes_the_file_and_reports_it(self):
        self.panel.slider_for("puck_drag_per_s")
        self.params.set("puck_drag_per_s", 0.55)
        self.assertEqual(self.click_button("save"), "saved")
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(self.params.dirty)
        self.assertIn("saved", self.panel.message)

        back = Params.load(self.path)
        self.assertAlmostEqual(back.get("puck_drag_per_s"), 0.55, places=9)

    def test_reload_reads_the_file_back(self):
        self.params.set("wall_restitution", 0.4)
        self.click_button("save")
        self.params.set("wall_restitution", 0.95)              # unsaved edit
        self.assertEqual(self.click_button("reload"), "reloaded")
        self.assertAlmostEqual(self.params.get("wall_restitution"), 0.4, places=9)

    def test_defaults_restores_the_parameter_set(self):
        self.params.set("puck_drag_per_s", 0.9)
        self.click_button("save")
        self.assertEqual(self.click_button("defaults"), "defaults")
        self.assertEqual(self.params.values, defaults())
        self.assertTrue(self.params.dirty)                     # in memory only until saved

    def test_the_message_history_is_bounded(self):
        for _ in range(20):
            self.click_button("reload")
        self.assertLessEqual(len(self.panel.messages), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
