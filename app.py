"""
app.py - TUI Interface for my-music-app

Responsibility:
 Provide a terminal user interface using Textual.
 Connects library.py (scanning) and player.py (playback).
 Handles all user input and display updates.
"""
from textual.app	import App, ComposeResult
from textual.widgets	import Header, Footer, ListView, ListItem, Label, Static
from textual.containers	import Horizontal, Vertical, ScrollableContainer
from textual.binding	import Binding
from textual.message	import Message

from library import scan_library, Library, Artist, Album, Track
from player  import MusicPlayer, PlaybackStatus

# -- CUSTOM MESSAGES -----------------------------------------------------------
# Textual uses a message-passing system for thread-safe communication.
# Our player runs a background thread - it cannot touch the UI directly
# Instead it posts these messages, and Textual delivers them safely.

class TrackChanged(Message):
 """Posted when the player moves to a new track."""
 def __init__(self, track: Track) -> None:
  self.track = track
  super().__init__()

class StateChanged(Message):
 """Posted when playback state changes (play/pause/stop/volume)."""
 pass


# -- MAIN APPLICATION --------------------------------------------------------

class MusicApp(App):
 """
 The root Textual application.
 All widgets are composed inside this class.
 """

 TITLE = "my-music-app"

 # Bindings appear in the Footer automatically
 BINDINGS = [
  Binding("space",		"toggle_pause",		"Play/Pause"),
  Binding("n",			  "next_track", 		"Next"),
  Binding("p",			  "prev_track",	  	"Prev"),
  Binding("up",			  "volume_up",		  "Vol+"),
  Binding("down",		  "volume_down",		"Vol-"),
  Binding("q",			  "quit",			      "Quit"),
 ]

 # TEXTUAL CSS -------------------------------------------------------------
 # Textual has its own CSS-like styling system
 # This control layout, colors, sizing, and spacing.

 DEFAULT_CSS = """
 /* -- ROOT LAYOUT -- */
 MusicApp{
  background: $surface;
 }

 /* -- SIDEBAR -- */
 #sidebar {
  width: 28;
  min-width: 20;
  border-right: solid $primary;
  background: $panel;
 }

 #sidebar-title-artists {
  background: $primary;
  color: $text;
  text-align: center;
  padding: 0 1;
 }

 #sidebar-title-albums {
  background: $primary;
  color: $text;
  text-align: center;
  padding: 0 1;
  margin-top: 1;
 }

 /* -- MAIN PANEL -- */
 #main-panel {
  background: $surface;
 }

 /* -- NOW PLAYING -- */
 #now-playing {
  height: auto;
  border: solid $accent;
  margin: 1 1 0 1;
  padding: 1 2;
  background: $panel;
  width: 100%;
 }

 #now-playing-title {
  text-style: bold;
  color: $accent;
 }

 #now-playing-artist-album {
  color: $text-muted;
 }

 #progress-bar {
  margin: 1 0 0 0;
  color: $accent;
  width: 100%;
 }

 #now-playing-time {
  color: $text-muted;
  margin-top: 0;
  width: 100%;
 }

 #now-playing-volume {
  color: $text-muted;
 }

 /* -- TRACKS PANEL -- */
 #tracks-title {
  background: $primary;
  color: $accent;
  text-align: center;
  padding: 0 1;
  margin: 1 1 0 1;
 }

 #tracks-list {
  margin: 0 1;
  border: solid $primary;
 }

 /* -- LIST ITEMS -- */
 ListView > ListItem {
  padding: 0 1;
 }

 ListView > ListItem.--highlight {
  background: $accent 20%;
 }

 ListView:focus > ListItem.--highlight {
  background: $accent 40%;
 }
 """

 # -- COMPOSE --------------------------------------------
 # compose() builds the widget tree.
 # This is Textual's equivalent of building a UI layout.

 def compose(self) -> ComposeResult:
  yield Header()

  with Horizontal():

   # -- LEFT SIDEBAR --
   with Vertical(id="sidebar"):
    yield Label("	ARTISTS", id="sidebar-title-artists")
    yield ListView(id="artist-list")
    yield Label("	ALBUMS", id="sidebar-title-albums")
    yield ListView(id="album-list")

   # -- RIGHT MAIN PANEL
   with Vertical(id="main-panel"):

    # NOW PLAYING SECTION
    with Vertical(id="now-playing"):
     yield Label("🎵 Nothing playing yet", id="now-playing-title")
     yield Label("", 		 	  id="now-playing-artist-album")
     yield Label("",			  id="progress-bar")
     yield Label("",			  id="now-playing-time")
     yield Label(" 🎤 Volume: 80%",	  id="now-playing-volume")

    # TRACKS SECTIONS
    yield Label("	TRACKS", id="tracks-title")
    yield ListView(id="track-list")

  yield Footer()

 # -- SAFE POSTING -------------------------------
 def _safe_post(self, message) -> None:
  """
  Post a message to Textual's event loop safely.
  Uses call_from_thread when called from a background thread,
  post_message when already on the main thread.
  """
  import threading
  if threading.current_thread() is threading.main_thread():
   self.post_message(message)
  else:
   self.call_from_thread(self.post_message, message)

 # -- ON MOUNT -----------------------------------
 # on_mount() runs once after the UI is fully built.
 # This is where we load data and wire up the player.

 def on_mount(self) -> None:
  """Initialize library, player, and start the progress updater."""

  # -- SCAN THE MUSIC LIBRARY --
  self.library = scan_library()
  self.player  = MusicPlayer()

  # Track which artist/album is currently selected in the sidebar
  self._selected_artist: Artist | None = None
  self._selected_album:  Album  | None = None
  self._populating = False

  # -- Register player callbacks --
  # These run from the player's background thread, so we use
  # call_from_thread() to safely post messages to the Textual event loop

  self.player.on_track_change(
   lambda t: self._safe_post(TrackChanged(t))
  )

  self.player.on_state_change(
   lambda s: self._safe_post(StateChanged())
  )


  # -- Populate the artist list --
  self._populate_artists()

  # -- Start the progress bar updater (every 500ms) --
  self.set_interval(0.25, self._update_progress)


 # -- POPULATE LISTS --------------------------------------

 def _populate_artists(self) -> None:
  """Fill the artist ListView from the scanned library."""
  artist_list = self.query_one("#artist-list", ListView)
  artist_list.clear()

  for index, artist in enumerate(self.library.artists):
   artist_list.append(
    ListItem(Label(artist.name), id=f"artist-{index}")
   )

 def _populate_albums(self, artist: Artist) -> None:
  """Fill the album ListView for the selected artist."""
  self._populating = True
  album_list = self.query_one("#album-list", ListView)
  album_list.clear()

  for album in artist.albums:
   album_list.append(ListItem(Label(album.name)))
  # for index, album in enumerate(artist.albums):
  #  album_list.append(
  #   ListItem(Label(album.name), id=f"album-{index}")
  #  )
  self._populating = False

 def _populate_tracks(self, album: Album) -> None:
  """Fill the track ListView for the selected album"""
  self._populating = True
  track_list = self.query_one("#track-list", ListView)
  track_list.clear()

  for track in album.tracks:
   label = f" {track.track_number:02d}. {track.title} [{track.duration_str}]"
   track_list.append(ListItem(Label(label)))

  # for index, track in enumerate(album.tracks):
  #  label = f"  {track.track_number:02d}, {track.title}  [{track.duration_str}]"
  #  track_list.append(
  #   ListItem(Label(label), id=f"track-{index}")
  #  )
  self._populating = False

 # -- LIST SELECTION HANDLERS -------------------------------
 # Textual calls these automatically when the user selects a list item.
 # The naming convention on_[widget_type]_selected is Textual's event system.

 def on_list_view_selected(self, event: ListView.Selected) -> None:
  """Handle selection in any of our three ListViews."""
  if self._populating:
   return

  list_id = event.list_view.id

  if list_id == "artist-list":
   self._on_artist_selected(event)
  elif list_id == "album-list":
   self._on_album_selected(event)
  elif list_id == "track-list":
   self._on_track_selected(event)

 def _on_artist_selected(self, event:ListView.Selected) -> None:
  """User selected an artist - load their albums."""
  index = event.list_view.index
  if index is None or index >= len(self.library.artists):
   return

  self._selected_artist = self.library.artists[index]
  self._populate_albums(self._selected_artist)

  # Clear the track list until they pick an album
  self.query_one("#track-list", ListView).clear()

 def _on_album_selected(self, event: ListView.Selected) -> None:
  """User selected an album - load its tracks."""
  if self._selected_artist is None:
   return

  index = event.list_view.index
  if index is None or index >= len(self._selected_artist.albums):
   return

  self._selected_album = self._selected_artist.albums[index]
  self._populate_tracks(self._selected_album)

  # Load this album into the player queue (doesn't start playing yet)
  self.player.load_queue(self._selected_album.artist)

 def _on_track_selected(self, event: ListView.Selected) -> None:
  """User selected a track - start playing from that position"""
  if self._selected_album is None:
   return

  index = event.list_view.index
  if index is None or index >= len(self._selected_album.tracks):
   return

  track = self._selected_album.tracks[index]
  self.player.load_queue(self._selected_album.tracks, start_index=index)
  self.player.play()


 # -- MESSAGE HANDLERS ----------------------------------
 # -- These handle the messages posted by our player callbacks.

 def on_track_changed(self, message: TrackChanged) -> None:
  """Update the Now PLaying panel when the track changes."""
  self._update_now_playing(message.track)

 def on_state_changed(self, message: StateChanged) -> None:
  """Refresh volume display when state changes."""
  volume_label = self.query_one("#now-playing-volume", Label)
  volume_label.update(f"🎤 Volume: {self.player.state.volume}%")

 # -- NOW PLAYING UPDATER

 def _update_now_playing(self, track: Track) -> None:
  """Refresh the Now Playing section with current track info."""
  self.query_one("#now-playing-title",		Label).update(f"🎵  {track.title}")
  self.query_one("#now-playing-artist-album", 	Label).update(f"    {track.artist} - {track.album}")

 def _update_progress(self) -> None:
  """
  Called every 500ms be set_interval.
  Updates the profress bar and time display.
  """  
  if self.player.state.status != PlaybackStatus.PLAYING:
   return

  track = self.player.state.current_track
  if track is None or track.duration <= 0:
   return

  position = self.player.state.position
  duration = track.duration
  percent  = position / duration

  # Build a simple ASCII progress bar - no external widgets needed
  bar_width = 30
  filled    = int(bar_width * percent)
  empty     = bar_width - filled
  # bar       = "🟩" * filled + "🏼" * empty
  bar       = "#" * filled + "-" * empty

  # Format times as mm:ss
  pos_min, pos_sec = divmod(int(position), 60)
  dur_min, dur_sec = divmod(int(duration), 60)

  self.query_one("#progress-bar",	    Label).update(f"     {bar}") # {percent:.0%}")
  self.query_one("#now-playing-time",	Label).update(
   f"     {pos_min}:{pos_sec:02d} / {dur_min}:{dur_sec:02d}"
  )


 # -- KEY BINDING ACTIONS -----------------------------------
 # Each action_* method maps to a BINDING defined above.

 def action_toggle_pause(self) -> None:
  """Space - play or pause, or restart queue if stopped."""
  if self.player.state.status == PlaybackStatus.STOPPED:
   # only attempt to play if we have a queue loaded
   if self.player.state.queue:
     self.player.play()
   return  
  self.player.pause()

 def action_next_track(self) -> None:
  """n - next track"""
  self.player.next_track()

 def action_prev_track(self) -> None:
  """p - previous track"""
  self.player.previous_track()

 def action_volume_up(self) -> None:
  """⬆ - increase volume by 10"""
  self.player.set_volume(self.player.state.volume + 10)

 def action_volume_down(self) -> None:
  """⬇ - decrease volume by 10"""
  self.player.set_volume(self.player.state.volume - 10)


 # -- UTILITIES ------------------------------------------

 @staticmethod
 def _safe_id(name: str) -> str:
  """
  Convert a name to a safe CSS/HTML id string.
  Textual widget IDs cannot contain spaces or special characters.
  """
  return name.lower().replace(" ", "-").replace("'", "").replace(".", "").replace("&", "").replace("!", "")

# -- ENTRY POINT ----------------------------------------

if __name__ == "__main__":
 app = MusicApp()
 app.run()