"""
pane_art.py — WezTerm Split Pane Album Art Display

Responsibility:
    Open a dedicated WezTerm pane for album art display.
    Render album art and track info into that pane.
    Clean up the pane on exit.

Requires:
    WezTerm terminal with CLI tools available.
    Only used when running inside WezTerm.
"""

import subprocess
import time
from pathlib import Path


class ArtPane:
    """
    Manages a dedicated WezTerm split pane for album art.

    Usage:
        pane = ArtPane()
        pane.open()                           # creates the split pane
        pane.display(art_path, artist, album) # renders art + info
        pane.close()                          # closes the pane on exit
    """

    def __init__(self):
        self._pane_id: int | None = None


    def open(self) -> bool:
        """
        Open a new split pane on the right side of the current WezTerm window.

        Uses WezTerm CLI to split the current pane:
            wezterm cli split-pane --right --percent 30

        --right     → new pane appears to the right
        --percent 30 → takes 30% of the window width

        Returns True if the pane was created successfully.
        The new pane ID is stored in self._pane_id.
        """
        try:
            result = subprocess.run(
                [
                    "wezterm", "cli", "split-pane",
                    "--right",
                    "--percent", "30"
                ],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                print(f"  ⚠️  Could not open art pane: {result.stderr.strip()}")
                return False

            # split-pane outputs the new pane's ID as a plain integer
            self._pane_id = int(result.stdout.strip())

            # Give the shell in the new pane a moment to initialise
            time.sleep(0.3)

            # Show a welcome message while we wait for the first track
            self._send_text("clear\r\n")
            time.sleep(0.1)
            # self._send_text("echo '🎵 Album Art'\r\n")

            return True

        except (ValueError, FileNotFoundError) as e:
            print(f"  ⚠️  Art pane open failed: {e}")
            return False


    def display(self, image_path: Path, artist: str, album: str) -> None:
        """
        Render album art and track info into the art pane.

        Steps:
            1. Clear the pane's current content
            2. Display the image using wezterm imgcat
            3. Print artist and album name below the image

        wezterm imgcat:
            --pane-id  → targets our specific pane
            image_path → the temp JPEG we fetched from MusicBrainz
        """
        if self._pane_id is None:
            return

        # Clear the pane before rendering new art
        self._clear()

        # Send imgcat as a command to the art pane's shell
        self._send_text(f"wezterm imgcat '{str(image_path)}'\r\n")

        # Print track info below the image
        self._send_text(
            f"'Album: {self._escape(album)}'\r\n"
        )



    def show_no_art(self, artist: str, album: str) -> None:
        """
        Show a text placeholder when no artwork is available.
        Called when MusicBrainz returns no art for this album.
        """
        if self._pane_id is None:
            return

        self._clear()
        self._send_text(
            f"echo ''\r\n"
            f"echo '  🎵 No artwork found'\r\n"
            f"echo ''\r\n"
            f"echo '  {self._escape(artist)}'\r\n"
            f"echo '  {self._escape(album)}'\r\n"
        )


    def close(self) -> None:
        """
        Close the art pane cleanly by exiting its shell.
        Called when the main app exits.
        """
        if self._pane_id is None:
            return

        self._send_text("exit\r\n")
        self._pane_id = None


    # ── INTERNAL HELPERS ──────────────────────────────────────────────────────

    def _clear(self) -> None:
        """Send a clear command to the art pane."""
        if self._pane_id is None:
            return
        self._send_text("clear\r\n")
        time.sleep(0.15)   # give the terminal time to process the clear


    def _send_text(self, text: str) -> None:
        """
        Send text to the art pane as if the user typed it.

        wezterm cli send-text:
            --pane-id   → targets our specific pane
            --no-paste  → sends as raw keystrokes, not clipboard paste
        """
        if self._pane_id is None:
            return

        subprocess.run(
            [
                "wezterm", "cli", "send-text",
                "--pane-id", str(self._pane_id),
                "--no-paste",
                text
            ],
            capture_output=True   # suppress output from this helper
        )


    @staticmethod
    def _escape(text: str) -> str:
        """
        Escape single quotes in text before embedding in shell echo commands.

        In bash, single-quoted strings can't contain single quotes.
        We replace ' with '"'"' which:
            '     closes the current single-quoted string
            "'"   opens a double-quoted string containing just '
            '     reopens the single-quoted string
        """
        return text.replace("'", "'\"'\"'")