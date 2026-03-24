"""
 library.py - Music Library Scanner for my-music-app

 Responsibility: 
	Scan a root music directory structured as:
	 Music Root/
	   Artist
	     Album
		track.m4a

	Build an in-memory respresentation of the library
	using Artist, Album, and Track dataclasses.

 No UI, no playback - purely data.
"""

from pathlib import Path
from dataclasses import dataclass, field
from mutagen.mp4 import MP4, MP4StreamInfoError
from mutagen.mp3 import MP3
from mutagen.id3 import ID3NoHeaderError

# -- CONFIGURATION ----------------------------

# The root folder where your music lives
MUSIC_ROOT = Path.home() / "Music"

# File extensions we'll treat as playable audio
SUPPORTED_EXTENSIONS = {".m4a", ".mp3", ".flac", ".ogg", ".opus"}

# -- DATA CLASSES ----------------------------
# Dataclasses are Python's clean way to define data-holding objects.
# The @dataclass decorator auto-generates __init__, __repr__, and more.

@dataclass
class Track:
	"""Represents a single audio file."""
	title:		str
	artist:		str
	album:		str
	track_number:	int
	duration:	float # in seconds
	file_path:	Path

	@property
	def duration_str(self) -> str:
		"""Returns duration as a human-readable string e.g. 3:41"""
		minutes, seconds = divmod(int(self.duration), 60)
		return f"{minutes}:{seconds:02d}"


@dataclass
class Album:
	"""Represents an album directory containing tracks."""
	name:       str
	artist:     str
	path:       Path
	tracks:     list[Track] = field(default_factory=list)

	@property
	def track_count(self) -> int:
		return len(self.tracks)

	@property
	def total_duration(self) -> float:
		return sum(t.duration for t in self.tracks)

	@property
	def total_duration_str(self) -> str:
		minutes, seconds = divmod(int(self.total_duration), 60)
		return f"{minutes}:{seconds:02d}"


@dataclass
class Artist:
	"""Represents an artist directory containing albums."""
	name:       str
	path:       Path
	albums:     list[Album] = field(default_factory=list)

	@property
	def album_count(self) -> int:
		return len(self.albums)

	@property
	def track_count(self) -> int:
		return sum(a.track_count for a in self.albums)


@dataclass
class Library:
	"""The complete in-memory music library."""
	root:   Path
	artists: list[Artist] = field(default_factory=list)

	@property
	def artist_count(self) -> int:
		return len(self.artists)

	@property
	def album_count(self) -> int:
		return sum(a.album_count for a in self.artists)

	@property
	def track_count(self) -> int:
		return sum(a.track_count for a in self.artists)


# -- METADATA READER ---------------------------

def read_track_metadata(file_path: Path, fallback_artist: str, fallback_album: str) -> Track | None:
	"""
	Read metadata from an audio file using mutagen.
	Handles M4A and MP3 formats with their respective tag systems.

	M4A uses Apple's MP4 atom format (© symbol keys)
	MP3 uses ID3 tags (TIT2, TPE1, TALB, TRCK keys)

	Falls back to folder names if tags are missing.
	Returns None if the file cannot be read.
	"""
	try:
		suffix = file_path.suffix.lower()

		if suffix == ".m4a":
			return _read_m4a_metadata(file_path, fallback_artist, fallback_album)
		elif suffix == ".mp3":
			return _read_mp3_metadata(file_path, fallback_artist, fallback_album)
		else:
			# Format in SUPPORTED_EXTENSIONS but no specific reader yet
			# We'll add more readers here as needed
			print(f" ⚠️  No metadata reader for format: {suffix}")
			return None

	except Exception as e:
		print(f" ⚠️  Unexpected error reading {file_path.name}: {e}")
		return None


def _read_m4a_metadata(file_path: Path, fallback_artist: str, fallback_album: str) -> Track | None:
	"""Read metadata from an M4A file."""

	try:
		audio = MP4(file_path)
		tags = audio.tags or {}

		title       = tags.get("\xa9nam", [file_path.stem])[0]
		artist      = tags.get("\xa9ART", [fallback_artist])[0]
		album       = tags.get("\xa9alb", [fallback_album])[0]
		track_number = tags.get("trkn", [(0,0)])[0][0]
		duration    = audio.info.length

		return Track(
			title       = title,
			artist      = artist,
			album       = album,
			track_number = track_number,
			duration    = duration,
			file_path   = file_path,
		)

	except MP4StreamInfoError:
		# File exists but is corrupt or not a real M4A
		print(f" ⚠️  Skipping corrupt file: {file_path.name}")
		return None


def _read_mp3_metadata(file_path: Path, fallback_artist: str, fallback_album: str) -> Track | None:
	"""
	Read metadata from an MP3 file.

	ID3 tag keys are very different from M4A:
	  TIT2 = Title
	  TPE1 = Artist (Lead performer)
	  TALB = Album
	  TRCK = Track number (may be "5" or "5/12" format)
	"""
	try:
		audio = MP3(file_path)
		tags = audio.tags

		if tags is None:
			# Valid MP3 but zero tags - fall back to folder/filename
			return Track(
				title       = file_path.stem,
				artist      = fallback_artist,
				album       = fallback_album,
				track_number = 0,
				duration    = audio.info.length,
				file_path   = file_path,
			)

		# ID3 tags return objects, not plain strings - str() extracts the value
		title   = str(tags.get("TIT2", file_path.stem))
		artist  = str(tags.get("TPE1", fallback_artist))
		album   = str(tags.get("TALB", fallback_album))

		# Track number can be "5" or "5/12" (track/total) - we want just the number
		raw_track = str(tags.get("TRCK", "0"))
		track_number = int(raw_track.split("/")[0]) if raw_track.isdigit() or "/" in raw_track else 0

		return Track(
			title       = title,
			artist      = artist,
			album       = album,
			track_number = track_number,
			duration    = audio.info.length,
			file_path   = file_path,
		)

	except ID3NoHeaderError:
		print(f" ⚠️  Skipping corrupt MP3: {file_path.name}")
		return None



# -- SCANNER -----------------------------

def scan_library(root: Path = MUSIC_ROOT) -> Library:
	"""
	Walk the music directory tree and build a Library object.

	Expected structure:
	  root/
		Artist Name/       <- depth 1
		  Album Name/     <- depth 2
			song.m4a      <- depth 3

	Uses pathlib.Path for clean, readable path handling.
	"""
	library = Library(root=root)

	if not root.exists():
		print(f"x Music root not found: {root}")
		return library

	if not root.is_dir():
		print(f"x Music root is not a directory: {root}")
		return library

	print(f"🔎 Scanning: {root}\n")

	# iterdir() lists immediate children of a directory
	# sorted() ensures consistent alphabetical ordering
	for artist_path in sorted(root.iterdir()):

		# Skip anything that isn't a directory (e.g. stray .DS_Store files)
		if not artist_path.is_dir():
			continue

		artist = Artist(name=artist_path.name, path=artist_path)

		for album_path in sorted(artist_path.iterdir()):
			if not album_path.is_dir():
				continue

			album = Album(
				name    = album_path.name,
				artist  = artist.name,
				path    = album_path,
			)

			# Find all supported audio files in this album directory
			# iterdir() only looks one level deep - intentional
			for file_path in sorted(album_path.iterdir()):
				if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
					continue

				track = read_track_metadata(
					file_path       = file_path,
					fallback_artist = artist.name,
					fallback_album  = album.name,
				)

				if track is not None:
					album.tracks.append(track)

			# Only add albums that actually contain playable tracks
			if album.track_count > 0:
				artist.albums.append(album)

		# Only add artists that have at least one album
		if artist.album_count > 0:
			library.artists.append(artist)

	return library

# -- QUICK SUMMARY PRINTER -----------------------------

def print_library_summary(library: Library) -> None:
	"""Print a readable summary of the scanned library."""
	print("-" * 50)
	print(f"📚 Library: {library.root}")
	print(f"  {library.artist_count} artist  |  "
		  f"{library.album_count}  albums  |  "
		  f"{library.track_count}  tracks")
	print("-" * 50)

	for artist in library.artists:
		print(f"\n 🎤 {artist.name}  ({artist.album_count} albums, {artist.track_count} tracks)")

		for album in artist.albums:
			print(f"  💿 {album.name}  - {album.track_count} tracks, {album.total_duration_str}")

			for track in album.tracks:
				print(f"    {track.track_number:02d}. {track.title}  [{track.duration_str}]")


# -- ENTRY POINT ------------------------------------
# This block only runs when you execute library.py directly
# When library.py is imported by other modules, this block is skipped.
# This pattern is fundamental Python - you'll use it constantly.

if __name__ == "__main__":
	library = scan_library()
	print_library_summary(library)
