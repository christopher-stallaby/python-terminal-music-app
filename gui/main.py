"""
gui/main.py — GTK4 GUI for my-music-app

Responsibility:
    Provide a native GNOME desktop interface using GTK4.
    Shares library.py, player.py, and art_fetcher.py with the TUI.

Requires:
    Python 3.12 (system) with PyGObject and GTK4
    Run from gui/ using: source venv/bin/activate && python3 main.py
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GdkPixbuf

import threading
import asyncio
from pathlib import Path

from library  import scan_library, Library, Artist, Album, Track
from player   import MusicPlayer, PlaybackStatus
from album_art import fetch_album_art, discard_album_art


# ── MAIN WINDOW ───────────────────────────────────────────────────────────────

class MusicWindow(Adw.ApplicationWindow):
    """
    The main application window.

    Adw.ApplicationWindow is libadwaita's window class — it gives us
    the native GNOME header bar, rounded corners, and theme integration
    automatically.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title("my-music-app")
        self.set_default_size(900, 600)

        # ── State ──
        self.library:           Library       = scan_library()
        self.player:            MusicPlayer   = MusicPlayer()
        self._selected_artist:  Artist | None = None
        self._selected_album:   Album  | None = None
        self._current_art_path: Path   | None = None
        self._progress_timer_id:int    | None = None

        # ── Build UI ──
        self._build_ui()

        # ── Wire player callbacks ──
        # GLib.idle_add schedules a function to run on the main GTK thread.
        # This is GTK's equivalent of Textual's call_from_thread —
        # we never touch widgets from a background thread directly.
        self.player.on_track_change(
            lambda t: GLib.idle_add(self._on_track_changed, t)
        )
        self.player.on_state_change(
            lambda s: GLib.idle_add(self._on_state_changed, s)
        )

        # ── Start progress updater ──
        # GLib.timeout_add calls a function every N milliseconds
        # on the main GTK thread — safe for widget updates
        self._progress_timer_id = GLib.timeout_add(500, self._update_progress)

        # ── Populate artist list ──
        self._populate_artists()


    # ── UI CONSTRUCTION ───────────────────────────────────────────────────────

    def _build_ui(self):
        """Build the complete widget tree."""

        # ── Header Bar ──
        header = Adw.HeaderBar()
        self.shuffle_btn = Gtk.ToggleButton(label="🔀")
        self.shuffle_btn.set_tooltip_text("Toggle Shuffle")
        self.shuffle_btn.connect("toggled", self._on_shuffle_toggled)
        header.pack_end(self.shuffle_btn)

        # ── Main layout: sidebar + content ──
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_position(220)

        # ── Sidebar ──
        sidebar = self._build_sidebar()
        self.paned.set_start_child(sidebar)

        # ── Right panel ──
        right_panel = self._build_right_panel()
        self.paned.set_end_child(right_panel)

        # ── Toolbar view wraps header + content ──
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(self.paned)

        self.set_content(toolbar_view)


    def _build_sidebar(self) -> Gtk.Widget:
        """Build the left sidebar with artist and album lists."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_size_request(200, -1)

        # Artists label
        artists_label = Gtk.Label(label="ARTISTS")
        artists_label.add_css_class("heading")
        artists_label.set_margin_top(12)
        artists_label.set_margin_bottom(6)
        box.append(artists_label)

        # Artist list
        self.artist_list = Gtk.ListBox()
        self.artist_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.artist_list.add_css_class("navigation-sidebar")
        self.artist_list.connect("row-selected", self._on_artist_selected)

        artist_scroll = Gtk.ScrolledWindow()
        artist_scroll.set_vexpand(True)
        artist_scroll.set_child(self.artist_list)
        box.append(artist_scroll)

        # Albums label
        albums_label = Gtk.Label(label="ALBUMS")
        albums_label.add_css_class("heading")
        albums_label.set_margin_top(12)
        albums_label.set_margin_bottom(6)
        box.append(albums_label)

        # Album list
        self.album_list = Gtk.ListBox()
        self.album_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.album_list.add_css_class("navigation-sidebar")
        self.album_list.connect("row-selected", self._on_album_selected)

        album_scroll = Gtk.ScrolledWindow()
        album_scroll.set_vexpand(True)
        album_scroll.set_child(self.album_list)
        box.append(album_scroll)

        return box


    def _build_right_panel(self) -> Gtk.Widget:
        """Build the right panel with now-playing and track list."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # ── Now Playing ──
        now_playing = self._build_now_playing()
        box.append(now_playing)

        # Separator
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Track list ──
        tracks_label = Gtk.Label(label="TRACKS")
        tracks_label.add_css_class("heading")
        tracks_label.set_margin_top(12)
        tracks_label.set_margin_bottom(6)
        box.append(tracks_label)

        self.track_list = Gtk.ListBox()
        self.track_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.track_list.add_css_class("rich-list")
        self.track_list.connect("row-activated", self._on_track_activated)

        track_scroll = Gtk.ScrolledWindow()
        track_scroll.set_vexpand(True)
        track_scroll.set_child(self.track_list)
        box.append(track_scroll)

        # ── Playback controls ──
        controls = self._build_controls()
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(controls)

        return box


    def _build_now_playing(self) -> Gtk.Widget:
        """Build the now-playing panel with art, title, and progress."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Album art image widget
        self.art_image = Gtk.Image()
        self.art_image.set_size_request(120, 120)
        self.art_image.set_pixel_size(120)
        self.art_image.add_css_class("icon-dropshadow")
        box.append(self.art_image)

        # Track info column
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_vexpand(True)
        info_box.set_valign(Gtk.Align.CENTER)

        self.title_label = Gtk.Label(label="Nothing playing yet")
        self.title_label.add_css_class("title-2")
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.set_ellipsize(3)   # PANGO_ELLIPSIZE_END
        info_box.append(self.title_label)

        self.artist_album_label = Gtk.Label(label="")
        self.artist_album_label.add_css_class("dim-label")
        self.artist_album_label.set_halign(Gtk.Align.START)
        info_box.append(self.artist_album_label)

        # Progress bar
        self.progress_bar = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1
        )
        self.progress_bar.set_draw_value(False)
        self.progress_bar.set_hexpand(True)
        self.progress_bar.connect("value-changed", self._on_seek)
        info_box.append(self.progress_bar)

        # Time label
        self.time_label = Gtk.Label(label="0:00 / 0:00")
        self.time_label.add_css_class("dim-label")
        self.time_label.set_halign(Gtk.Align.START)
        info_box.append(self.time_label)

        box.append(info_box)
        return box


    def _build_controls(self) -> Gtk.Widget:
        """Build the playback control toolbar."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_halign(Gtk.Align.CENTER)

        # Previous
        prev_btn = Gtk.Button(label="⏮")
        prev_btn.connect("clicked", lambda _: self.player.previous_track())
        prev_btn.add_css_class("circular")
        box.append(prev_btn)

        # Play/Pause
        self.play_btn = Gtk.Button(label="⏯")
        self.play_btn.connect("clicked", self._on_play_pause)
        self.play_btn.add_css_class("circular")
        self.play_btn.add_css_class("suggested-action")
        box.append(self.play_btn)

        # Next
        next_btn = Gtk.Button(label="⏭")
        next_btn.connect("clicked", lambda _: self.player.next_track())
        next_btn.add_css_class("circular")
        box.append(next_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        box.append(spacer)

        # Volume
        volume_label = Gtk.Label(label="🔊")
        box.append(volume_label)

        self.volume_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1
        )
        self.volume_scale.set_value(80)
        self.volume_scale.set_size_request(120, -1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.connect("value-changed", self._on_volume_changed)
        box.append(self.volume_scale)

        return box


    # ── POPULATE LISTS ────────────────────────────────────────────────────────

    def _populate_artists(self):
        """Fill the artist ListBox from the scanned library."""
        for artist in self.library.artists:
            row = Gtk.Label(label=artist.name)
            row.set_halign(Gtk.Align.START)
            row.set_margin_top(6)
            row.set_margin_bottom(6)
            row.set_margin_start(6)
            self.artist_list.append(row)

    def _populate_albums(self, artist: Artist):
        """Fill the album ListBox for the selected artist."""
        # Remove all existing rows
        while row := self.album_list.get_row_at_index(0):
            self.album_list.remove(row)

        for album in artist.albums:
            row = Gtk.Label(label=album.name)
            row.set_halign(Gtk.Align.START)
            row.set_margin_top(6)
            row.set_margin_bottom(6)
            row.set_margin_start(6)
            self.album_list.append(row)

    def _populate_tracks(self, album: Album):
        """Fill the track ListBox for the selected album."""
        while row := self.track_list.get_row_at_index(0):
            self.track_list.remove(row)

        for track in album.tracks:
            label = Gtk.Label(
                label=f"{track.track_number:02d}.  {track.title}  [{track.duration_str}]"
            )
            label.set_halign(Gtk.Align.START)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_margin_start(6)
            self.track_list.append(label)


    # ── SELECTION HANDLERS ────────────────────────────────────────────────────

    def _on_artist_selected(self, listbox, row):
        if row is None:
            return
        self._selected_artist = self.library.artists[row.get_index()]
        self._populate_albums(self._selected_artist)

        # Clear track list
        while r := self.track_list.get_row_at_index(0):
            self.track_list.remove(r)

    def _on_album_selected(self, listbox, row):
        if row is None or self._selected_artist is None:
            return
        self._selected_album = self._selected_artist.albums[row.get_index()]
        self._populate_tracks(self._selected_album)
        self.player.load_queue(self._selected_album.tracks)

    def _on_track_activated(self, listbox, row):
        if row is None or self._selected_album is None:
            return
        index = row.get_index()
        track = self._selected_album.tracks[index]
        self.player.load_queue(self._selected_album.tracks, start_index=index)
        self.player.play()


    # ── PLAYER EVENT HANDLERS ─────────────────────────────────────────────────

    def _on_track_changed(self, track: Track):
        """Update UI when track changes — always called on main GTK thread."""
        self.title_label.set_label(track.title)
        self.artist_album_label.set_label(f"{track.artist}  —  {track.album}")
        self.progress_bar.set_range(0, track.duration)

        # Discard previous art
        if self._current_art_path:
            discard_album_art(self._current_art_path)
            self._current_art_path = None
            self.art_image.clear()

        # Fetch new art in background thread
        threading.Thread(
            target=self._fetch_art_thread,
            args=(track.artist, track.album),
            daemon=True
        ).start()

        return False   # required by GLib.idle_add


    def _on_state_changed(self, state):
        """Update play button icon when state changes."""
        if state.status == PlaybackStatus.PLAYING:
            self.play_btn.set_label("⏸")
        else:
            self.play_btn.set_label("▶")
        return False


    # ── ALBUM ART ─────────────────────────────────────────────────────────────

    def _fetch_art_thread(self, artist: str, album: str):
        """
        Fetch album art in a background thread.

        GTK widgets cannot be touched from background threads —
        we fetch the art here, then schedule the display update
        on the main thread using GLib.idle_add.
        """
        loop     = asyncio.new_event_loop()
        art_path = loop.run_until_complete(fetch_album_art(artist, album))
        loop.close()

        if art_path:
            # Schedule widget update on main GTK thread
            GLib.idle_add(self._display_art, art_path)


    def _display_art(self, art_path: Path):
        """Display album art — called on main GTK thread via idle_add."""
        try:
            texture = Gdk.Texture.new_from_filename(str(art_path))
            self.art_image.set_from_paintable(texture)
            self._current_art_path = art_path
        except Exception as e:
            print(f"  ⚠️  Could not display art: {e}")
            discard_album_art(art_path)

        return False   # required by GLib.idle_add


    # ── CONTROLS ──────────────────────────────────────────────────────────────

    def _on_play_pause(self, button):
        if self.player.state.status == PlaybackStatus.STOPPED:
            if self.player.state.queue:
                self.player.play()
        else:
            self.player.pause()

    def _on_shuffle_toggled(self, button):
        self.player.toggle_shuffle()

    def _on_volume_changed(self, scale):
        self.player.set_volume(int(scale.get_value()))

    def _on_seek(self, scale):
        """Seek to position when user drags the progress bar."""
        self.player.seek(scale.get_value())

    def _update_progress(self) -> bool:
        """
        Update progress bar and time label every 500ms.
        Returns True to keep the timer running — returning False stops it.
        This is how GLib.timeout_add works.
        """
        if self.player.state.status != PlaybackStatus.PLAYING:
            return True

        track = self.player.state.current_track
        if track is None:
            return True

        position = self.player.state.position
        duration = track.duration

        # Block signal to prevent _on_seek firing during programmatic update
        self.progress_bar.handler_block_by_func(self._on_seek)
        self.progress_bar.set_value(position)
        self.progress_bar.handler_unblock_by_func(self._on_seek)

        pos_min, pos_sec = divmod(int(position), 60)
        dur_min, dur_sec = divmod(int(duration), 60)
        self.time_label.set_label(
            f"{pos_min}:{pos_sec:02d}  /  {dur_min}:{dur_sec:02d}"
        )

        return True   # keep timer running


# ── APPLICATION ───────────────────────────────────────────────────────────────

class MusicApp(Adw.Application):
    """
    The GTK application object.
    Adw.Application handles the app lifecycle, theming, and
    ensures only one instance runs at a time.
    """

    def __init__(self):
        super().__init__(application_id="com.mymusic.app")
        self.connect("activate", self._on_activate)

    def _on_activate(self, app):
        win = MusicWindow(application=app)
        win.present()


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = MusicApp()
    app.run()
