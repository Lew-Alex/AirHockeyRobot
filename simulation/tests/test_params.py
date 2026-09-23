"""Parameter model: defaults, clamping, the file round trip, and the effect on the world."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena import Arena                                    # noqa: E402
from input import ForceController                          # noqa: E402
from mallet import Mallet                                  # noqa: E402
from params import BY_KEY, SCHEMA, Params, defaults        # noqa: E402
from puck import Puck                                      # noqa: E402
from world import World, make_world                        # noqa: E402

DT = 1.0 / 1000.0


class TempFileMixin(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "params.json")

    def tearDown(self):
        self._dir.cleanup()


class TestSchema(unittest.TestCase):
    def test_every_default_is_inside_its_own_range(self):
        for param in SCHEMA:
            self.assertGreaterEqual(param.default, param.minimum, param.key)
            self.assertLessEqual(param.default, param.maximum, param.key)

    def test_keys_are_unique(self):
        keys = [p.key for p in SCHEMA]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_serve_is_gentle_by_default(self):
        """Alex asked for a slow serve: the puck coming at you at full pace on the first
        look is not useful. This is a guard on that preference, not a physics limit."""
        self.assertLessEqual(BY_KEY["serve_speed_m_s"].default, 1.5)
        self.assertGreater(BY_KEY["serve_speed_m_s"].default, 0.0)
        self.assertGreaterEqual(BY_KEY["serve_speed_m_s"].maximum, 10.0)   # pace is available

    def test_the_parameters_asked_about_are_present(self):
        for key in ("puck_drag_per_s", "mallet_restitution", "wall_restitution",
                    "puck_mass_kg", "belt_speed_limit_m_s", "controller_stiffness"):
            self.assertIn(key, BY_KEY)


class TestClamping(TempFileMixin):
    def test_set_clamps_high_and_low(self):
        p = Params(path=self.path)
        self.assertEqual(p.set("mallet_restitution", 5.0), 1.0)
        self.assertEqual(p.set("mallet_restitution", -3.0), 0.0)
        self.assertEqual(p.set("puck_drag_per_s", 99.0), BY_KEY["puck_drag_per_s"].maximum)

    def test_get_and_index(self):
        p = Params(path=self.path)
        self.assertEqual(p.get("time_scale"), 1.0)
        self.assertEqual(p["time_scale"], 1.0)

    def test_unknown_key_raises(self):
        p = Params(path=self.path)
        with self.assertRaises(KeyError):
            p.set("not_a_parameter", 1.0)

    def test_first_edit_marks_it_dirty(self):
        p = Params(path=self.path)
        self.assertFalse(p.dirty)
        p.set("puck_drag_per_s", 0.5)
        self.assertTrue(p.dirty)


class TestFile(TempFileMixin):
    def test_save_then_load_round_trip(self):
        p = Params(path=self.path)
        p.set("puck_drag_per_s", 0.42)
        p.set("wall_restitution", 0.33)
        p.set("goal_width_in", 20.0)
        p.save()
        self.assertFalse(p.dirty)

        back = Params.load(self.path)
        self.assertAlmostEqual(back.get("puck_drag_per_s"), 0.42, places=9)
        self.assertAlmostEqual(back.get("wall_restitution"), 0.33, places=9)
        self.assertAlmostEqual(back.get("goal_width_in"), 20.0, places=9)
        self.assertFalse(back.dirty)

    def test_the_file_is_readable_json_with_a_note(self):
        p = Params(path=self.path)
        p.save()
        with open(self.path) as handle:
            raw = json.load(handle)
        self.assertEqual(raw["version"], 1)
        self.assertIn("note", raw)
        self.assertEqual(set(raw["values"]), set(defaults()))

    def test_construct_and_apply_never_write_anything(self):
        """Only an explicit save touches the disk. A stray parameter file appearing in the
        repo because something called apply() would be a nasty surprise mid-run."""
        target = os.path.join(self._dir.name, "never_written.json")
        p = Params(path=target)
        p.set("puck_drag_per_s", 0.4)
        p.apply(make_world(), ForceController(mallet_index=0))
        p.get("puck_drag_per_s")
        self.assertFalse(os.path.exists(target))
        p.save()
        self.assertTrue(os.path.exists(target))

    def test_a_missing_file_gives_the_defaults(self):
        p = Params.load(os.path.join(self._dir.name, "nothing_here.json"))
        self.assertEqual(p.values, defaults())
        self.assertFalse(p.dirty)

    def test_a_corrupt_file_gives_the_defaults_rather_than_raising(self):
        with open(self.path, "w") as handle:
            handle.write("{ this is not json")
        p = Params.load(self.path)
        self.assertEqual(p.values, defaults())

    def test_unknown_keys_are_ignored(self):
        with open(self.path, "w") as handle:
            json.dump({"values": {"puck_drag_per_s": 0.2, "laser_power": 9000}}, handle)
        p = Params.load(self.path)
        self.assertAlmostEqual(p.get("puck_drag_per_s"), 0.2, places=9)
        self.assertNotIn("laser_power", p.values)

class TestOutOfRangeFile(TempFileMixin):
    def test_a_hand_edited_file_cannot_leave_the_range(self):
        with open(self.path, "w") as handle:
            json.dump({"values": {"mallet_restitution": 12.0, "puck_mass_kg": -1.0}}, handle)
        p = Params.load(self.path)
        self.assertEqual(p.get("mallet_restitution"), 1.0)
        self.assertEqual(p.get("puck_mass_kg"), BY_KEY["puck_mass_kg"].minimum)

    def test_reload_picks_up_an_external_edit(self):
        p = Params(path=self.path)
        p.save()
        with open(self.path, "w") as handle:
            json.dump({"values": {"puck_drag_per_s": 0.9}}, handle)
        p.reload()
        self.assertAlmostEqual(p.get("puck_drag_per_s"), 0.9, places=9)
        self.assertFalse(p.dirty)

    def test_reset_to_defaults_marks_it_dirty(self):
        p = Params(path=self.path)
        p.set("puck_drag_per_s", 0.5)
        p.save()
        p.reset_to_defaults()
        self.assertEqual(p.values, defaults())
        self.assertTrue(p.dirty)


class TestEffectOnTheWorld(unittest.TestCase):
    def setUp(self):
        self.world = make_world()
        self.controller = ForceController(mallet_index=0)

    def test_drag_reaches_the_puck(self):
        p = Params()
        p.set("puck_drag_per_s", 0.9, mark_dirty=False)
        p.apply(self.world)
        self.assertAlmostEqual(self.world.puck.drag_per_s, 0.9, places=9)

    def test_a_tired_blower_slows_the_puck_measurably(self):
        def glide(drag):
            world = make_world()
            params = Params()
            params.set("puck_drag_per_s", drag, mark_dirty=False)
            params.apply(world, self.controller)
            world.puck.launch(0.1, world.arena.centre_y, 6.0, 0.0)
            for _ in range(300):
                world.step()
            return world.puck.speed

        self.assertLess(glide(1.0), 0.8 * glide(0.0))

    def test_restition_reaches_the_mallet_and_changes_the_return(self):
        def struck(e):
            world = make_world()
            params = Params()
            params.set("mallet_restitution", e, mark_dirty=False)
            params.apply(world, self.controller)
            world.puck.launch(0.45, world.arena.centre_y, 0.0, 0.0)
            world.mallets[0].teleport(0.2, world.arena.centre_y)
            for _ in range(2000):
                world.set_force(0, 300.0, 0.0)
                world.step()
                if world.event == "mallet":
                    return world.puck.speed
            return 0.0

        self.assertLess(struck(0.1), struck(0.9))

    def test_wall_restitution_reaches_the_arena(self):
        p = Params()
        p.set("wall_restitution", 1.0, mark_dirty=False)
        p.apply(self.world)
        self.assertAlmostEqual(self.world.arena.wall_restitution, 1.0, places=9)

        self.world.puck.launch(0.5, 0.02, 0.0, -4.0)
        self.world.step()
        # an elastic wall returns the speed it was hit with, less the drag inside the step
        self.assertAlmostEqual(self.world.puck.vy, 4.0, delta=1e-3)

    def test_the_belt_limit_sets_both_mallet_limits(self):
        p = Params()
        p.set("belt_speed_limit_m_s", 4.0, mark_dirty=False)
        p.apply(self.world, self.controller)
        mallet = self.world.mallets[0]
        self.assertAlmostEqual(mallet.axial_speed_limit_m_s, 4.0, places=9)
        self.assertAlmostEqual(mallet.diagonal_speed_limit_m_s, 4.0 / 2 ** 0.5, places=9)

        for _ in range(3000):
            mallet.apply_force(400.0, 0.0, DT)
        self.assertAlmostEqual(mallet.speed, 4.0, places=9)

    def test_mass_reaches_every_mallet_and_the_puck(self):
        p = Params()
        p.set("puck_mass_kg", 0.04, mark_dirty=False)
        p.set("mallet_mass_kg", 1.2, mark_dirty=False)
        p.apply(self.world, self.controller)
        self.assertAlmostEqual(self.world.puck.mass_kg, 0.04, places=9)
        for mallet in self.world.mallets:
            self.assertAlmostEqual(mallet.mass_kg, 1.2, places=9)
            self.assertAlmostEqual(mallet.effective_mass_kg, 1.2, places=9)

    def test_a_heavier_mallet_transfers_more_into_the_puck(self):
        """Driven at the same contact speed, a heavier mallet is closer to the
        infinite-mass limit and so sends the puck away faster. Driving both with the same
        force would confuse this with the acceleration effect: the lighter mallet would
        reach the cap sooner."""
        def post(mass):
            world = make_world()
            params = Params()
            params.set("mallet_mass_kg", mass, mark_dirty=False)
            params.set("mallet_restitution", 0.7, mark_dirty=False)
            params.apply(world, self.controller)
            r_sum = world.puck.radius + world.mallets[0].radius
            world.puck.launch(0.45, world.arena.centre_y, 0.0, 0.0)
            world.mallets[0].teleport(0.45 - (r_sum + 0.002), world.arena.centre_y)
            world.mallets[0].set_velocity(5.0, 0.0)      # the same contact speed for both
            for _ in range(200):
                world.step()
                if world.event == "mallet":
                    return world.puck.speed
            return 0.0

        self.assertGreater(post(2.0), post(0.3))

    def test_a_lighter_mallet_reaches_the_cap_sooner_under_the_same_force(self):
        """Compared before either one saturates the belt cap, otherwise both read 10.0."""
        def speed_after(mass, steps=15):
            mallet = Mallet()
            mallet.mass_kg = mass
            for _ in range(steps):
                mallet.apply_force(300.0, 0.0, DT)
            return mallet.speed

        self.assertGreater(speed_after(0.2), speed_after(2.0))

    def test_control_gains_reach_the_controller(self):
        p = Params()
        p.set("controller_stiffness", 123.0, mark_dirty=False)
        p.set("controller_damping", 7.0, mark_dirty=False)
        p.set("controller_max_force", 99.0, mark_dirty=False)
        p.apply(self.world, self.controller)
        self.assertAlmostEqual(self.controller.stiffness_n_per_m, 123.0, places=9)
        self.assertAlmostEqual(self.controller.damping_n_per_m_s, 7.0, places=9)
        self.assertAlmostEqual(self.controller.max_force_n, 99.0, places=9)

    def test_geometry_parameters_reach_the_objects(self):
        p = Params()
        p.set("puck_radius_m", 0.04, mark_dirty=False)
        p.set("mallet_radius_m", 0.05, mark_dirty=False)
        p.set("goal_width_in", 18.0, mark_dirty=False)
        p.apply(self.world, self.controller)
        self.assertAlmostEqual(self.world.puck.radius, 0.04, places=9)
        self.assertAlmostEqual(self.world.mallets[0].radius, 0.05, places=9)
        self.assertAlmostEqual(self.world.arena.goal_width_in, 18.0, places=9)


class TestObjectsAcceptLiveEdits(unittest.TestCase):
    def test_an_arena_can_be_edited_in_place(self):
        arena = Arena()
        arena.wall_restitution = 0.5
        self.assertAlmostEqual(arena.wall_restitution, 0.5)

    def test_puck_and_mallet_attributes_are_live(self):
        puck = Puck()
        mallet = Mallet()
        puck.drag_per_s = 0.5
        mallet.restitution = 0.2
        self.assertAlmostEqual(puck.drag_per_s, 0.5)
        self.assertAlmostEqual(mallet.restitution, 0.2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
