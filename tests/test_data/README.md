# Test Data

This directory contains official test files for the Hollow Knight Discord Bot.

## Save Files

### `fresh_save.dat`
- **Source**: `%WinAppDataLocalLow%Team Cherry_Hollow Knight_user1.dat`
- **Description**: Fresh Hollow Knight save file
- **Characteristics**:
  - Playtime: 0.32 hours (19.4 minutes)
  - Completion: 0.0%
  - Geo: 54
  - Health: 5/5
  - Location: Town
  - Deaths: 0

### `midgame_save.dat`
- **Source**: `user1 (1).dat`
- **Description**: Mid-game Hollow Knight save file
- **Characteristics**:
  - Playtime: 6.52 hours
  - Completion: 55%
  - Geo: 3,120
  - Health: 7/9 hearts
  - Location: City_Storerooms (CITY zone)
  - Deaths: 27

## Usage

These files are used by the test suite to verify:
- Save file decryption functionality
- Data parsing accuracy
- Progress analysis generation
- Error handling for different save states

## File Format

Both files are encrypted Hollow Knight save files (`.dat` format) that can be decrypted using the `hollow_knight_decrypt.py` module.
