## ADDED Requirements

### Requirement: Session 6 YouTube metadata file
The project SHALL include `output/session 6/youtube.md` with YouTube upload metadata following the established format from Sessions 3 v2 and 5.

#### Scenario: YouTube file structure
- **WHEN** `output/session 6/youtube.md` is read
- **THEN** it contains sections: Title, Description (with tracklist and timestamps), Tags, and Thumbnail Text Ideas

### Requirement: YouTube title format
The YouTube title SHALL follow the pattern: `Deep Session 06 // <subtitle> — A Dark Techno Mix [<genre tags>]`

#### Scenario: Title format
- **WHEN** the title is read
- **THEN** it matches the pattern `Deep Session 06 // <name> — A Dark Techno Mix [Dark Techno / Industrial]`

### Requirement: YouTube description with tracklist
The description SHALL include a thematic intro paragraph, total duration, narrative arc description, clickable timestamped tracklist, technical notes, and hashtags.

#### Scenario: Clickable timestamps
- **WHEN** the tracklist section is read
- **THEN** each track has a timestamp in `MM:SS` format corresponding to its actual start time in the mix

#### Scenario: Genre-appropriate tone
- **WHEN** the description intro is read
- **THEN** the copy uses dark, industrial, underground language appropriate for dark techno (not warm/cozy)

### Requirement: YouTube tags for discovery
The tags section SHALL include relevant dark techno discovery terms.

#### Scenario: Tag coverage
- **WHEN** the tags are read
- **THEN** they include: dark techno, industrial techno, techno mix, underground techno, warehouse techno, hard techno, coding music, focus music, DJ mix

**Primary files**: `output/session 6/youtube.md` (new)
