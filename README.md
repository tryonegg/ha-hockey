# Hockey

A Home Assistant custom integration that tracks a hockey team's next, current,
or most recent game and exposes it as a sensor and a game-event entity. A
separate [Lovelace card](https://github.com/tryonegg/ha-hockey-card) displays it as a scorebug.

## Features

- Supported leagues: NHL, PWHL, AHL, OHL, WHL, QMJHL, or any other
  HockeyTech-powered league via your own API key and client code.
- One device per tracked team, with a sensor for the game state and an event
  entity for in-game events (goals, period changes, power plays, final score,
  etc.).
- Per-team scorebug colors, configurable in the integration's options and
  exposed as sensor attributes for the card to use.

## Installation

### HACS (custom repository)

1. In Home Assistant, open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/tryonegg/ha-hockey` with category **Integration**.
3. Install **Hockey**, then restart Home Assistant.

### Manual

Copy `custom_components/hockey` from this repository into
`<config>/custom_components/hockey`, then restart Home Assistant.

## Requirements

Home Assistant 2024.12.0 or newer.

## Setup

Go to **Settings → Devices & Services → Add Integration**, search for
**Hockey**, choose a league, and pick the team to track.

## Options

Per tracked team (**Configure** on the integration entry), you can set:

- **Show a finished game for (hours)**: default 9, counted from the estimated
  end of the game (about three hours after puck drop).
- **Hide the previous result when the next game is within (hours)**: default 6.
  Set to 0 to never show the previous result.
- **Home / away background, text and accent colors**, with a reset to the
  team's default palette. NHL and PWHL teams ship with defaults; other leagues
  have none until you set them.

## Lovelace card

The integration does not load or register any frontend code. To show the
scorebug, install the card from its own repository:

1. In HACS, open **⋮ → Custom repositories**.
2. Add `https://github.com/tryonegg/ha-hockey-card` with category
   **Dashboard** (plugin).
3. Install it, then add it to a dashboard:

   ```yaml
   type: custom:hockey-scorebug-card
   entity: sensor.nhl_new_jersey_devils
   ```

See the [card's README](https://github.com/tryonegg/ha-hockey-card) for all options.