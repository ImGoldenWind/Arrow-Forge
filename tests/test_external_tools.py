import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import external_tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ExternalToolsTests(unittest.TestCase):
    def test_managed_pe_detection(self):
        self.assertTrue(
            external_tools._is_managed_pe(
                str(PROJECT_ROOT / "tools" / "VGAudioCLI" / "VGAudioCli.exe")
            )
        )
        self.assertTrue(
            external_tools._is_managed_pe(
                str(PROJECT_ROOT / "tools" / "CPKForge" / "CPKForge.exe")
            )
        )
        self.assertFalse(
            external_tools._is_managed_pe(
                str(PROJECT_ROOT / "tools" / "Sofdec2" / "sofdec2enc.exe")
            )
        )

    def test_dotnet_dll_command(self):
        with patch.object(external_tools, "_dotnet_runtime", return_value="/usr/bin/dotnet"):
            self.assertEqual(
                external_tools.tool_command("/opt/tools/VGAudioCli.dll"),
                ["/usr/bin/dotnet", "/opt/tools/VGAudioCli.dll"],
            )

    def test_windows_exe_command_uses_runner_on_posix(self):
        with (
            patch.object(external_tools.os, "name", "posix"),
            patch.object(external_tools, "_exe_runner", return_value="/usr/bin/wine"),
        ):
            self.assertEqual(
                external_tools.tool_command("/opt/tools/ffmpeg.exe"),
                ["/usr/bin/wine", "/opt/tools/ffmpeg.exe"],
            )

    def test_managed_exe_prefers_mono_and_native_pe_uses_wine(self):
        vgaudio = str(PROJECT_ROOT / "tools" / "VGAudioCLI" / "VGAudioCli.exe")
        sofdec = str(PROJECT_ROOT / "tools" / "Sofdec2" / "sofdec2enc.exe")
        with (
            patch.object(external_tools.os, "name", "posix"),
            patch.object(external_tools, "_mono_runtime", return_value="/usr/bin/mono"),
            patch.object(external_tools, "_wine_runtime", return_value="/usr/bin/wine"),
        ):
            self.assertEqual(external_tools._exe_runner(vgaudio), "/usr/bin/mono")
            self.assertEqual(external_tools._exe_runner(sofdec), "/usr/bin/wine")

    def test_find_tool_honors_platform_name_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled = Path(temp_dir) / "ffmpeg"
            bundled.mkdir()
            windows_tool = bundled / "ffmpeg.exe"
            windows_tool.touch()
            native_tool = str(Path(temp_dir) / "system" / "ffmpeg")

            def which(name):
                return native_tool if name == "ffmpeg" else None

            with (
                patch.object(external_tools, "_tools_roots", return_value=[temp_dir]),
                patch.object(external_tools.shutil, "which", side_effect=which),
                patch.object(
                    external_tools,
                    "_is_runnable",
                    side_effect=lambda path: path == native_tool or Path(path).is_file(),
                ),
            ):
                found = external_tools.find_tool(
                    "ffmpeg", "ffmpeg.exe", subdirs=("ffmpeg",)
                )

            self.assertEqual(found, native_tool)

    def test_bundled_native_tool_recovers_user_execute_bit(self):
        fake_stat = Mock(st_mode=stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        with (
            patch.object(external_tools.os, "name", "posix"),
            patch.object(external_tools.os, "access", return_value=False),
            patch.object(external_tools, "_is_bundled_tool", return_value=True),
            patch.object(external_tools.os, "stat", return_value=fake_stat),
            patch.object(external_tools.os, "chmod") as chmod,
        ):
            external_tools._ensure_bundled_executable("/opt/arrow-forge/tools/rhubarb")

        chmod.assert_called_once_with(
            "/opt/arrow-forge/tools/rhubarb",
            fake_stat.st_mode | stat.S_IXUSR,
        )


if __name__ == "__main__":
    unittest.main()
