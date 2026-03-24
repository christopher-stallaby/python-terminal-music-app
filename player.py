"""
 player.py - Audio Playback Engine for my-music-app

 Responsibility:
  Control audio playback using python-vlc.
  Manage a queue of tracks.
  Notify other parts of the app when playback state changes.

 No UI, no file scanning - purely playback control.
"""

import vlc
import time
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable
from library import Track

# -- PLAYBACK STATE  -----------------------
class PlaybackStatus(Enum):
    """
    Enum representing every possible state the player can be in.
    Enums are better than plain strings for state - typos become errors,
    not silent bugs.
    """
    STOPPED = auto()
    PLAYING = auto()
    PAUSED  = auto()

@dataclass
class PlayerState:
    """
    A snapshot of the player at any moment in time.
    The TUI will read this to know what to display.
    """
    status:         PlaybackStatus  = PlaybackStatus.STOPPED
    current_track:  Track | None    = None
    queue:          list[Track]     = field(default_factory=list)
    queue_index:    int             = 0
    volume:         int             = 80 # 0-100
    position:       float           = 0.0 # seconds into current track

# -- MUSIC PLAYER ------------------------
class MusicPlayer:
    """
    Wraps python-vlc to provide clean, simple playback control.

    Usage:
        player = MusicPlayer()
        player.load_queue(list_of_tracks)
        player.play()
    """

    def __init__(self):
        # vlc.Instance is the VLC engine itself
        # '--quiet' suppresses VLC's own log output to the terminal
        self._instance = vlc.Instance("--quiet")

        # MediaPlayer is what actually plays audio
        self._media_player = self._instance.media_player_new()

        # Our state object - the single source of truth
        self.state = PlayerState()

        # Callbacks - functions to call when events happen
        # Other modules (like the TUI) register their functions here
        self._on_track_change_callbacks:    list[Callable] = []
        self._on_track_end_callbacks:       list[Callable] = []
        self._on_state_change_callbacks:    list[Callable] = []

        # Start the background thread that watches for track endings
        self._monitor_thread = threading.Thread(
            target=self._monitor_playback,
            daemon=True,   # daemon=True means this thread dies when the app exits
            name="PlaybackMonitor"
        )
        self._monitor_thread.start()


    # -- QUEUE MANAGEMENT ----------------------------
    def load_queue(self, tracks: list[Track], start_index: int = 0) -> None:
        """
        Load a list of tracks as the playback queue.
        Optionally start at a specific index.
        """
        self.stop()
        self.state.queue        = tracks
        self.state.queue_index  = start_index


    # -- PLAYBACK CONTROLS --------------------------
    def play(self, track: Track | None = None) -> None:
        """
        Play a specific track, or resume/start the current queue position.
        """
        if track is not None:
            # Find this track in the queue so our index stays accurate
            if track in self.state.queue:
                self.state.queue_index = self.state.queue.index(track)
            self._play_track(track)
            return
        
        # No track specified - play  from current queue position
        if not self.state.queue:
            return
        
        if self.state.status == PlaybackStatus.PAUSED:
            self._media_player.play()
            self.state.status = PlaybackStatus.PLAYING
            self._notify_state_change()
            return
        
        self._play_track(self.state.queue[self.state.queue_index])

    def pause(self) -> None:
        """Toggle between paused and playing"""
        if self.state.status == PlaybackStatus.PLAYING:
            self._media_player.pause()
            self.state.status = PlaybackStatus.PAUSED
            
        elif self.state.status == PlaybackStatus.PAUSED:
            self._media_player.play()
            self.state.status = PlaybackStatus.PLAYING

        self._notify_state_change()

    def stop(self) -> None:
        """Stop playback completely."""
        self._media_player.stop()
        self.state.status           = PlaybackStatus.STOPPED
        self.state.current_track    = None
        self.state.position         = 0.0
        self._notify_state_change()


    def next_track(self) -> None:
        """Advance to next track in the queue."""
        if not self.state.queue:
            return
        
        next_index = self.state.queue_index + 1

        if next_index >= len(self.state.queue):
            # We're are the end of the queue - stop
            self.stop()
            return
        
        self.state.queue_index = next_index
        self._play_track(self.state.queue[self.state.queue_index])

    def previous_track(self) -> None:
        """
        Go to the previous track, or restart the current track
        if more than 3 seconds in - like every good music player does.
        """
        if not self.state.queue:
            return
        
        if self.state.position > 3.0:
            # Restart the current track
            self.seek(0)
            return
        
        prev_index = self.state.queue_index -1

        if prev_index < 0:
            # Already at the first track - restart it
            self.seek(0)
            return
    
        self.state.queue_index = prev_index
        self._play_track(self.state.queue[self.state.queue_index])

    def set_volume(self, volume: int) -> None:
        """Set volume. Accepts 0-100"""
        volume = max(0, min(100, volume)) # clamp to valid range
        self.state.volume = volume
        self._media_player.audio_set_volume(volume)
        self._notify_state_change()


    def seek(self, seconds: float) -> None:
        """Jump to a position in the current track (in seconds)."""
        if self.state.current_track is None:
            return

        duration = self.state.current_track.duration
        if duration <= 0:
            return
        
        # VLC seeks using a position between 0.0 and 1.0
        position = max(0.0, min(1.0, seconds / duration))
        self._media_player.set_position(position)
        self.state.position = seconds

    # -- CALLBACK REGISTRATION ------------------------------
    # These allow the TUI to "subscribe" to player events.
    # This pattern is called the Observer Pattern.

    def on_track_change(self, callback: Callable) -> None:
        """Register a function to call when the track changes."""
        self._on_track_change_callbacks.append(callback)

    def on_track_end(self, callback: Callable) -> None:
        """Register a function to call when a track finishes."""
        self._on_track_end_callbacks.append(callback)

    def on_state_change(self, callback: Callable) -> None:
        """"Register a function to call when playback state changes."""
        self._on_state_change_callbacks.append(callback)


    # -- INTERNAL METHODS ----------------------------------
    def _play_track(self, track: Track) -> None:
        """Internal method - loads and plays a specific track."""
        self._media_player.stop()

        # Create a new media object pointing to the file
        media = self._instance.media_new(str(track.file_path))
        self._media_player.set_media(media)
        self._media_player.audio_set_volume(self.state.volume)

        # Pre-buffer briefly before playing to reduce initial hiccup
        time.sleep(0.1)
        self._media_player.play()

        self.state.current_track    = track
        self.state.status           = PlaybackStatus.PLAYING
        self.state.position         = 0.0

        self._notify_track_change()
        self._notify_state_change()

    def _get_current_position(self) -> float:
        """Get current playback position in seconds."""
        if self.state.current_track is None:
            return 0.0
        
        vlc_position = self._media_player.get_position() # 0.0 to 1.0
        if vlc_position < 0:
            return 0.0
        
        return vlc_position * self.state.current_track.duration

    def _monitor_playback(self) -> None:
        """
        Background thread that watches for track endings and updates position.

        Runs every 500ms — lightweight enough to not impact performance,
        fast enough to feel responsive.

        This is why we use daemon=True — this loop runs forever,
        but dies automatically when the main app exits.
        """
        while True:
            time.sleep(0.5)

            if self.state.status != PlaybackStatus.PLAYING:
                continue

            # Update position
            self.state.position = self._get_current_position()

            # Check if VLC has finished playing
            vlc_state = self._media_player.get_state()

            if vlc_state == vlc.State.Ended:
                self._notify_track_end()
                # Small delay to avoid firing the event multiple times
                time.sleep(0.5)
                self.next_track()

    
    # -- NOTIFIERS ------------------------------------

    def _notify_track_change(self) -> None:
        for callback in self._on_track_change_callbacks:
            callback(self.state.current_track)

    def _notify_track_end(self) -> None:
        for callback in self._on_track_end_callbacks:
            callback(self.state.current_track)
    
    def _notify_state_change(self) -> None:
        for callback in self._on_state_change_callbacks:
            callback(self.state)
    

# -- ENTRY POINT -------------------------------------

if __name__ == "__main__":
    from library import scan_library

    print("🎵 Testing MusicPlayer...\n")

    library = scan_library()

    if not library.artists:
        print("❌ No music found — check your MUSIC_ROOT in library.py")
        exit(1)

    # Grab the first album's tracks as our test queue
    first_artist = library.artists[0]
    first_album  = first_artist.albums[0]
    test_queue   = first_album.tracks

    print(f"▶  Playing: {first_artist.name} — {first_album.name}")
    print(f"    {len(test_queue)} tracks in queue\n")

    player = MusicPlayer()

    # Register a simple callback so we can see events firing
    player.on_track_change(lambda t: print(f"\n🎵 Now playing: {t.track_number:02d}. {t.title}  [{t.duration_str}]"))
    player.on_track_end(lambda t:   print(f"    ✅ Finished:   {t.title}"))

    player.load_queue(test_queue)
    player.play()

    print("Controls: [n] next [p] previous [space] pause [q] quit [0-9] volume\n")

    # Simple keyboard control loop for testing
    import sys
    import tty
    import termios

    def get_keypress():
        """Read a single keypress without requiring Enter."""
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    while True:
        key = get_keypress()

        if key == 'q':
            player.stop()
            print("\n👋 Stopped.")
            break
        elif key == 'n':
            player.next_track()
        elif key == 'p':
            player.previous_track()
        elif key == ' ':
            player.pause()
            status = "⏸ Paused" if player.state.status == PlaybackStatus.PAUSED else "▶ Playing"
            print(f"\n{status}")
        elif key in '0123456789':
            vol = int(key) * 10
            player.set_volume(vol)
            print(f"\n🔊 Volume: {vol}%")
