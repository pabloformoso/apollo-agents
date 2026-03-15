## 1. Font & Static Assets

- [ ] 1.1 Download Share Tech Mono font and save to `fonts/ShareTechMono-Regular.ttf`
  <!-- Files: fonts/ShareTechMono-Regular.ttf -->

## 2. Dark Techno Artwork Prompt

- [ ] 2.1 Add `"dark-techno"` entry to `ARTWORK_PROMPTS` dict with industrial/warehouse DALL-E 3 prompt template including `{track_name}` placeholder
  <!-- Files: main.py -->

## 3. Session 6 Configuration

- [ ] 3.1 Create `tracks/session 6/` directory structure
  <!-- Files: tracks/session 6/ -->
- [ ] 3.2 Create `tracks/session 6/session.json` with session name "Session 6 — Dark Techno", description, and theme block (ShareTechMono font, #FF1744 red title, [5,2,8] bg, [255,23,68] waveform, [255,50,80] particles, bg_darken 0.7, artwork_style "dark-techno")
  <!-- Files: tracks/session 6/session.json -->
- [ ] 3.3 Define curated playlist with ~20 dark techno tracks: atmospheric intro → tension build → peak energy → breakdown → dark closer
  <!-- Files: tracks/session 6/session.json -->
- [ ] 3.4 Assign Camelot keys to all tracks for harmonic mixing compatibility
  <!-- Files: tracks/session 6/session.json -->
- [ ] 3.5 Assign genre tags to all tracks (Dark Techno, Industrial Techno, Acid Techno, Hard Techno, Ambient Techno)
  <!-- Files: tracks/session 6/session.json -->

## 4. Track Generation

- [ ] 4.1 Generate ~20 dark techno WAV tracks via Suno AI (128-140 BPM range, dark/industrial character)
  <!-- Files: tracks/session 6/*.wav -->
- [ ] 4.2 Verify all WAV files referenced in session.json exist and are valid audio
  <!-- Files: tracks/session 6/*.wav -->

## 5. YouTube Metadata

- [ ] 5.1 Create `output/session 6/` directory
  <!-- Files: output/session 6/ -->
- [ ] 5.2 Create `output/session 6/youtube.md` with title following pattern: `Deep Session 06 // <subtitle> — A Dark Techno Mix [Dark Techno / Industrial]`
  <!-- Files: output/session 6/youtube.md -->
- [ ] 5.3 Write YouTube description with dark/industrial thematic intro, total duration, narrative arc, and genre-appropriate tone
  <!-- Files: output/session 6/youtube.md -->
- [ ] 5.4 Add timestamped tracklist section with MM:SS format timestamps calculated from track durations and crossfade overlap
  <!-- Files: output/session 6/youtube.md -->
- [ ] 5.5 Add technical notes, hashtags, tags, and thumbnail text ideas sections
  <!-- Files: output/session 6/youtube.md -->

## 6. Validation

- [ ] 6.1 Verify `python main.py 6` loads session.json and lists all tracks without errors
  <!-- Files: main.py, tracks/session 6/session.json -->
- [ ] 6.2 Verify the dark-techno artwork prompt template is accessible and formats correctly with a sample track name
  <!-- Files: main.py -->
- [ ] 6.3 Verify Share Tech Mono font loads correctly via PIL/Pillow
  <!-- Files: main.py, fonts/ShareTechMono-Regular.ttf -->
