# Tally Lilliput RM209 + ATEM SuperSource Setup

## Overview
Auto-sync tally lights (red PGM, green PVW, off otherwise) for 6 Lilliput RM209 screens (3 bandeaux, 2 each) with Blackmagic ATEM. Supports SuperSource (ID 6000) + 4 PIP. Uses Companion triggers + Python UDP bridge.

## Requirements
- Bitfocus Companion v4.1+.
- Python 3.8+.
- ATEM switcher (IP connected).
- 3 RM209 bandeaux (IPs: 192.168.1.109/110/111).

## Install
1. **Python Bridge**: Save `tally_bridge.py`, run `python tally_bridge.py`. Test: `http://localhost:8080/?state=rouge&band=1&id=1` (light on).

2. **Companion Configs**: Import `expression-variables-*.companionconfig` and `triggers-*.companionconfig` (Variables/Triggers tabs).

3. **ATEM & HTTP**: Add ATEM connection (IP switcher). Add "Generic HTTP Requests" > Base URL `http://localhost:8080`.

## Test
- PGM CAM1: Red on screen 1 band 1.
- PVW CAM1: Green.
- SuperSource PGM + CAM1 in Box1: Red.
- Cut: Off.

## Debug
- Logs: Companion View > Logs ("expression evaluated").
- Firewall: Allow UDP 19522/23.

## Files
- `tally_bridge.py`: UDP polling bridge.
- Configs: Companion JSON for vars/triggers.

Questions? Bitfocus forum or f.roger@mattlaprod.com
Enjoy your tally setup!
