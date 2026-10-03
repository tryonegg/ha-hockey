# Hockey Sensor

A Home Assistant custom integration that tracks a hockey team's next, current,
or most recent game and exposes it as a sensor and game events. A
separate [Lovelace card](https://github.com/tryonegg/ha-hockey-card) displays it as a scorebug.

## Features

- Supported leagues: NHL, PWHL, AHL, OHL, WHL, QMJHL, or any other
  HockeyTech-powered league via your own API key and client code.
- One device per tracked team, with a sensor for the game state and an event
  entity for in-game events (goals, period changes, power plays, final score,
  etc.). See [Game events](#game-events) for the full list.
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

## Entities

Each tracked team is one device with two entities:

- **Sensor** (`sensor.<league>_<team>`): the game state, with the full game
  data (teams, scores, period, clock, situation, colors) as attributes. It
  covers the next, current or most recent game. The Lovelace card reads it.
- **Event entity** (`event.<league>_<team>_events`): fires an event for each
  thing that happens in the game, described below.

Polling adapts to the game: hourly when idle, every 60 seconds in the 15
minutes before puck drop, and every 15 seconds while the game is live.

## Game events

The event entity fires one of the following event types. Use it in an
automation with an **Event** trigger (or `trigger: state` on the entity with
the `event_type` attribute).

| Event type | Fires when |
| --- | --- |
| `pregame` | Puck drop is within 15 minutes. |
| `game_start` | Play begins in the first period. |
| `period_start` | Play begins in a later period. |
| `period_end` | A period ends. |
| `goal` | Your team scores. |
| `opponent_goal` | The opponent scores. |
| `goal_overturned` | One of your team's goals is taken back (for example after a review). |
| `opponent_goal_overturned` | An opponent goal is taken back. |
| `power_play` | Your team goes on a power play. NHL only. |
| `penalty_kill` | Your team goes shorthanded. NHL only. |
| `goalie_pulled` | Your team pulls its goalie in the third period while trailing. NHL only. |
| `overtime` | The game is level after regulation and overtime begins. |
| `shootout` | A shootout begins. HockeyTech leagues does not announce this live, so it is NHL only. |
| `final` | The game ends. |
| `win` | The game ended and your team won. Follows `final`. |
| `loss` | The game ended and your team lost. Follows `final`. |

Power play, penalty kill and goalie pulled depend on on-ice data that
HockeyTech leagues (PWHL, AHL, OHL, WHL, QMJHL and custom) do not publish, so
they never fire for those leagues.

Every event carries these attributes:

| Attribute | Meaning |
| --- | --- |
| `game_id` | The league's id for the game. |
| `team` / `opponent` | Team abbreviations. |
| `team_score` / `opponent_score` | Scores at the time of the event. For goal events this is the score after (or, for an overturned goal, back to) that goal. |
| `period` | Current period. For `period_end` it is the period that just ended. |
| `game_state` | The feed's game state. |
| `game_type` | `preseason`, `regular` or `playoffs`. |

Some events add more: `final`, `win` and `loss` include `decided_in`
(`REG`, `OT` or `SO`), and `power_play` and `penalty_kill` include `strength`
(for example 5v4).

Restarting Home Assistant in the middle of a game does not replay events that
already happened. A game that has no scheduled opponent yet fires nothing.

Example automation:

```yaml
triggers:
  - trigger: event.received
    target:
      entity_id: event.nhl_new_jersey_devils_events
    options:
      event_type:
        - goal
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room
    data:
      flash: long
```

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