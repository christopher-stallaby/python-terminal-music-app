import vlc
import time
from mutagen.mp4 import MP4

# -- CONFIG -------------------------------
TEST_FILE = "/home/chris/Music/Avicii/True/01 Wake Me Up.m4a"
PLAY_DURATION = 10 #seconds
# -----------------------------------------

def test_metadata():
	print("\n-- METADATA TEST ---------")
	audio = MP4(TEST_FILE)

	# M4A tag names are unusual - these are standard MP4 tag keys
	title = audio.tags.get("\xa9nam", ["Unknown Title"])[0]
	artist = audio.tags.get("\xa9ART", ["Unknown Artist"])[0]
	album = audio.tags.get("\xa9alb", ["Unknown Album"])[0]
	track = audio.tags.get("trkn",  [(0,0)])[0][0]

	print(f"  Title:  {title}")
	print(f"  Artist:  {artist}")
	print(f"  Album:  {album}")
	print(f"  Track:  {track}")
	print("----------------------------------------\n")


def test_playback():
	print("--- PLAYBACK TEST -----------------")
	print(f"   Playing for {PLAY_DURATION} seconds...")

	instance = vlc.Instance()
	player = instance.media_player_new()
	media = instance.media_new(TEST_FILE)

	player.set_media(media)
	player.play()

	time.sleep(PLAY_DURATION)

	player.stop()
	print("  Playback stopped cleanly.")
	print("-------------------------------\n")

if __name__ == "__main__":
	print("\n🎵 my-music-app - Stack Verification Test")
	test_metadata()
	test_playback()
	print("✅ All test passed!\n")
