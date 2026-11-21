"""Windows launch/forwarding checks without a phone, ADB server, GUI or Android build."""

import subprocess
import unittest
from unittest.mock import call, patch

import view_puck_stream_windows as launcher


class WindowsLauncherTests(unittest.TestCase):
    def test_reuses_and_preserves_existing_forward(self):
        with patch.object(launcher, "adb_run", return_value="pixel tcp:8765 tcp:8765") as adb, \
                patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as process:
            command = [r"C:\Python With Spaces\python.exe", r"C:\My Tools\view_puck_stream.py",
                       "--report", r"C:\Test Reports\puck.json"]
            self.assertEqual(launcher.run_viewer("adb.exe", "pixel", 8765, command), 0)
            process.assert_called_once_with(command)
            adb.assert_called_once_with("adb.exe", "forward", "--list")

    def test_conflicting_forward_is_never_replaced(self):
        with patch.object(launcher, "adb_run", return_value="another-phone tcp:8765 tcp:9000") as adb, \
                patch.object(launcher.subprocess, "run") as process:
            with self.assertRaisesRegex(RuntimeError, "already forwards"):
                launcher.run_viewer("adb.exe", "pixel", 8765, ["python", "viewer.py"])
            process.assert_not_called()
            adb.assert_called_once_with("adb.exe", "forward", "--list")

    def test_new_forward_is_cleaned_even_when_viewer_fails(self):
        with patch.object(launcher, "adb_run", side_effect=["", "", "pixel tcp:8766 tcp:8765", ""]) as adb, \
                patch.object(launcher.subprocess, "run", side_effect=OSError("viewer unavailable")):
            with self.assertRaises(OSError):
                launcher.run_viewer("adb.exe", "pixel", 8766, ["python", "viewer.py"])
            self.assertEqual(adb.call_args_list, [
                call("adb.exe", "forward", "--list"),
                call("adb.exe", "-s", "pixel", "forward", "--no-rebind", "tcp:8766", "tcp:8765"),
                call("adb.exe", "forward", "--list"),
                call("adb.exe", "-s", "pixel", "forward", "--remove", "tcp:8766"),
            ])

    def test_usb_transport_is_selected_and_pinned_to_serial(self):
        with patch.object(launcher, "adb_run", side_effect=["device", "pixel-serial"]) as adb:
            self.assertEqual(launcher.select_device("adb.exe"), "pixel-serial")
            self.assertEqual(adb.call_args_list, [call("adb.exe", "-d", "get-state"),
                                                 call("adb.exe", "-d", "get-serialno")])

    def test_unauthorized_phone_has_actionable_error(self):
        with patch.object(launcher, "adb_run", side_effect=[RuntimeError("unauthorized"), "pixel unauthorized"]):
            with self.assertRaisesRegex(RuntimeError, "approve its authorization prompt"):
                launcher.select_device("adb.exe")


if __name__ == "__main__":
    unittest.main()
