"""Default team colours: two sweaters per club, background/text/accent each.

Derived from each club's actual home (dark) and away (white) sweater colours,
cross-checked for WCAG AA text contrast (4.5:1) and reduced to three roles a
side: `background` and `text` are the safe, AA-verified reading pair; `accent`
is a third brand tone for rules, borders, and other non-text uses, so it is not
itself contrast-checked. Every value can be overridden per team in the
integration options.

Keyed by the team id each config entry stores - the abbreviation for the NHL,
the numeric HockeyTech id for the PWHL.
"""
from typing import Any, Dict, List, Optional, Tuple

# (home background, home text, home accent, away background, away text, away accent)
COLOR_KEYS = ("home_background", "home_text", "home_accent", "away_background", "away_text", "away_accent")


TEAM_COLORS: Dict[str, Dict[str, Tuple[str, str, str, str, str, str]]] = {
    "nhl": {
        "ANA": ("#b5985a", "#000000", "#f47a38", "#ffffff", "#000000", "#f47a38"),  # Anaheim Ducks — home 7.60:1 / away 21.00:1
        "BOS": ("#fcb514", "#000000", "#fcb514", "#ffffff", "#000000", "#fcb514"),  # Boston Bruins — home 11.76:1 / away 21.00:1
        "BUF": ("#002654", "#ffffff", "#fcb514", "#ffffff", "#002654", "#fcb514"),  # Buffalo Sabres — home 14.94:1 / away 14.94:1
        "CAR": ("#cc0000", "#ffffff", "#a4a9ad", "#ffffff", "#cc0000", "#a4a9ad"),  # Carolina Hurricanes — home 5.89:1 / away 5.89:1
        "CBJ": ("#041e42", "#ffffff", "#c8102e", "#ffffff", "#041e42", "#ce1126"),  # Columbus Blue Jackets — home 16.54:1 / away 16.54:1
        "CGY": ("#ce1126", "#ffffff", "#f3bc52", "#ffffff", "#ce1126", "#f3bc52"),  # Calgary Flames — home 5.63:1 / away 5.63:1
        "CHI": ("#ce1126", "#ffffff", "#000000", "#ffffff", "#ce1126", "#000000"),  # Chicago Blackhawks — home 5.63:1 / away 5.63:1
        "COL": ("#236192", "#ffffff", "#6f263d", "#ffffff", "#236192", "#6f263d"),  # Colorado Avalanche — home 6.57:1 / away 6.57:1
        "DAL": ("#006341", "#ffffff", "#a2aaad", "#ffffff", "#006341", "#a2aaad"),  # Dallas Stars — home 7.34:1 / away 7.34:1
        "DET": ("#c8102e", "#ffffff", "#c8102e", "#ffffff", "#c8102e", "#c8102e"),  # Detroit Red Wings — home 5.88:1 / away 5.88:1
        "EDM": ("#041e42", "#ffffff", "#fc4c02", "#ffffff", "#041e42", "#fc4c02"),  # Edmonton Oilers — home 16.54:1 / away 16.54:1
        "FLA": ("#c8102e", "#ffffff", "#041e42", "#ffffff", "#c8102e", "#041e42"),  # Florida Panthers — home 5.88:1 / away 5.88:1
        "LAK": ("#010101", "#ffffff", "#a2aaad", "#ffffff", "#010101", "#a2aaad"),  # Los Angeles Kings — home 20.87:1 / away 20.87:1
        "MIN": ("#154734", "#ffffff", "#a6192e", "#ffffff", "#154734", "#a6192e"),  # Minnesota Wild — home 10.59:1 / away 10.59:1
        "MTL": ("#a6192e", "#ffffff", "#001e62", "#ffffff", "#a6192e", "#001e62"),  # Montreal Canadiens — home 7.50:1 / away 7.50:1
        "NJD": ("#c8102e", "#ffffff", "#010101", "#ffffff", "#c8102e", "#010101"),  # New Jersey Devils — home 5.88:1 / away 5.88:1
        "NSH": ("#ffb81c", "#000000", "#ffb81c", "#ffffff", "#041e42", "#ffb81c"),  # Nashville Predators — home 12.12:1 / away 16.54:1
        "NYI": ("#00539b", "#ffffff", "#fc4c02", "#ffffff", "#00539b", "#fc4c02"),  # New York Islanders — home 7.75:1 / away 7.75:1
        "NYR": ("#0033a0", "#ffffff", "#c8102e", "#ffffff", "#0033a0", "#c8102e"),  # New York Rangers — home 10.60:1 / away 10.60:1
        "OTT": ("#c8102e", "#ffffff", "#c69214", "#ffffff", "#c8102e", "#c69214"),  # Ottawa Senators — home 5.88:1 / away 5.88:1
        "PHI": ("#fa4616", "#010101", "#010101", "#ffffff", "#fa4616", "#010101"),  # Philadelphia Flyers — home 5.92:1 / away 3.53:1
        "PIT": ("#ffb81c", "#000000", "#ffb81c", "#ffffff", "#000000", "#ffb81c"),  # Pittsburgh Penguins — home 12.12:1 / away 21.00:1
        "SEA": ("#001628", "#ffffff", "#99d9d9", "#ffffff", "#001628", "#99d9d9"),  # Seattle Kraken — home 18.33:1 / away 18.33:1
        "SJS": ("#006D75", "#ffffff", "#EA7200", "#ffffff", "#006D75", "#EA7200"),  # San Jose Sharks — home 6.10:1 / away 6.10:1
        "STL": ("#002F87", "#ffffff", "#FCB514", "#ffffff", "#002F87", "#FCB514"),  # St. Louis Blues — home 11.96:1 / away 11.96:1
        "TBL": ("#002868", "#ffffff", "#002868", "#ffffff", "#002868", "#002868"),  # Tampa Bay Lightning — home 13.97:1 / away 13.97:1
        "TOR": ("#00205b", "#ffffff", "#596e94", "#ffffff", "#00205b", "#596e94"),  # Toronto Maple Leafs — home 15.47:1 / away 15.47:1
        "UTA": ("#5f9acc", "#ffffff", "#5f9acc", "#ffffff", "#5f9acc", "#5f9acc"),  # Utah Mammoth — home 3.01:1 / away 3.01:1
        "VAN": ("#00205b", "#ffffff", "#00843d", "#ffffff", "#00205b", "#00843d"),  # Vancouver Canucks — home 15.47:1 / away 15.47:1
        "VGK": ("#B4975A", "#333f42", "#333f42", "#ffffff", "#a78d54", "#333f42"),  # Vegas Golden Knights — home 3.89:1 / away 3.19:1
        "WPG": ("#041E42", "#ffffff", "#004C97", "#ffffff", "#041e42", "#004c97"),  # Winnipeg Jets — home 16.54:1 / away 16.54:1
        "WSH": ("#041E42", "#ffffff", "#C8102E", "#ffffff", "#041E42", "#C8102E"),  # Washington Capitals — home 16.54:1 / away 16.54:1
    },
    "pwhl": {
        "1": ("#173F35", "#ffffff", "#B5E3D8", "#ffffff", "#173f35", "#B5E3D8"),  # Boston Fleet — home 11.67:1 / away 11.67:1
        "2": ("#250E62", "#ffffff", "#A77BCA", "#ffffff", "#250E62", "#A77BCA"),  # Minnesota Frost — home 15.94:1 / away 15.94:1
        "3": ("#862633", "#E1D3C4", "#041E42", "#ffffff", "#862633", "#041E42"),  # Montréal Victoire — home 6.12:1 / away 8.98:1
        "4": ("#00BFB3", "#041E42", "#ED8B00", "#ffffff", "#041E42", "#ED8B00"),  # New York Sirens — home 7.17:1 / away 16.54:1
        "5": ("#A6192E", "#ffffff", "#FFB81C", "#ffffff", "#A6192E", "#FFB81C"),  # Ottawa Charge — home 7.50:1 / away 7.50:1
        "6": ("#0067B9", "#ffffff", "#FFB81C", "#ffffff", "#0067B9", "#FFB81C"),  # Toronto Sceptres — home 5.77:1 / away 5.77:1
        "8": ("#0A5458", "#ffffff", "#5a92a8", "#ffffff", "#0A5458", "#5a92a8"),  # Seattle Torrent — home 8.67:1 / away 8.67:1
        "9": ("#10457F", "#EEE9D8", "#A76741", "#ffffff", "#10457F", "#A76741"),  # Vancouver Goldeneyes — home 7.93:1 / away 9.63:1
        "10": ("#000000", "#ffffff", "#C02B2D", "#ffffff", "#000000", "#C02B2D"),  # PWHL Detroit — home 21.00:1 / away 21.00:1
        "11": ("#f2a900", "#000000", "#64111D", "#ffffff", "#64111D", "#64111D"),  # PWHL Hamilton — home 10.45:1 / away 12.81:1
        "12": ("#717237", "#ffffff", "#FAAC2E", "#ffffff", "#717237", "#FAAC2E"),  # PWHL Las Vegas — home 5.04:1 / away 5.04:1
        "13": ("#F69245", "#000000", "#0774CE", "#ffffff", "#d37d3c", "#0774CE"),  # PWHL San Jose — home 9.12:1 / away 3.10:1
    },
}





def default_colors(league: Optional[str], team_id: Any) -> Optional[Dict[str, str]]:
    """The shipped palette for a team, or None if the league has none."""
    preset = TEAM_COLORS.get(str(league or ""), {}).get(str(team_id))
    if not preset:
        return None
    return dict(zip(COLOR_KEYS, preset))


def rgb_to_hex(value: Any) -> Optional[str]:
    """Convert the [r, g, b] a colour selector returns into #rrggbb."""
    if isinstance(value, str) and value.startswith("#"):
        return value.lower()
    try:
        r, g, b = (max(0, min(255, int(c))) for c in value)
    except (TypeError, ValueError):
        return None
    return "#%02x%02x%02x" % (r, g, b)


def hex_to_rgb(value: Optional[str]) -> Optional[List[int]]:
    """Convert #rrggbb into the [r, g, b] a colour selector expects."""
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return None
    try:
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return None


def resolve_colors(league: Optional[str], team_id: Any, options: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Final colours for a team: shipped defaults with any overrides applied.

    Returns None when nothing is known, so a league without a palette and
    without overrides leaves the card on the dashboard theme.
    """
    resolved = default_colors(league, team_id) or {}
    for key in COLOR_KEYS:
        override = rgb_to_hex((options or {}).get("color_" + key))
        if override:
            resolved[key] = override
    return resolved or None


def matchup_colors(
    league: Optional[str],
    home: Dict[str, Any],
    away: Dict[str, Any],
    tracked_side: Optional[str],
    tracked_colors: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """Primary (home sweater) colours of both teams in a game, by side.

    The split layout paints each half in that side's own team colour, so it
    needs the opponent's palette too. The tracked team keeps any overrides
    from the options; the opponent gets the shipped defaults. Sides with no
    known palette are left out, and the card falls back to its own surface.
    """
    out: Dict[str, str] = {}
    for side, team in (("home", home), ("away", away)):
        if side == tracked_side and tracked_colors:
            palette = tracked_colors
        else:
            key = (team or {}).get("abbr") if league == "nhl" else (team or {}).get("id")
            palette = default_colors(league, key)
        if not palette:
            continue
        for part in ("background", "text"):
            value = palette.get("home_" + part)
            if value:
                out[f"{side}_team_{part}"] = value
    return out
