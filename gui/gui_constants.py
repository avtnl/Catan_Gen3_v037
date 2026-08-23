"""
Defines GUI-related constants for the Catan game.

This module provides fonts, colors, images, sounds, and positioning constants for consistent
rendering of the playboard, scoreboard, and buttons.

Classes:
    Font: Enumeration for font sizes with bold support.
    Color: Enumeration for color values.
    PlayerColor: Enumeration for player color mappings.
    Sound: Enumeration for sound effects.
    Image: Enumeration for image assets.

Constants:
    COLORS: Dictionary of color names to RGB tuples.
    REVERSE_COLOR_MAPPING: Dictionary of color mappings for game logic.
    SOUNDS: Dictionary of sound effect names to Pygame Sound objects.
    IMAGES: Dictionary of image asset names to scaled Pygame Surfaces.
    WIN: Pygame display surface for rendering.
    BOARD_OFFSET: Tuple for offsetting board elements.
    PANEL_OFFSET: Tuple for offsetting panel elements.
    PANEL_OFFSET_Y2: Y-offset for secondary panel elements.
    UI_PANEL_LAYOUT: Named pygame.Rect regions for major GUI panels.
    UI_PANEL_LAYOUT_NOTES: Human-readable overview of major GUI regions.
    POSITIONS: Dictionary of tile, intersection, button, and panel positions.
    UI_PANEL_LAYOUT: Named major GUI and scoreboard sub-panel rectangles.

Dependencies:
    - pygame: For font, image, and sound handling.
    - pathlib: For file path management.
    - typing: For type hints.
    - enum: For enumerations.
    - core.constants: For logging constants.
"""
import pygame
from pathlib import Path
from typing import Dict, Optional, Tuple, Union
from enum import Enum
from core.constants import MG, FILENAME_MG

# Import-time path banner: headless dig-in only (DEBUG / -v). Interactive stays quiet.
try:
    from core.console import digin, DEBUG, is_no_gui

    if is_no_gui():
        digin(f"Loading gui_constants.py from: {__file__}", level=DEBUG)
except Exception:
    pass


def is_audio_enabled() -> bool:
    """Return True when sound effects may play.

    Policy: ``NO_GUI_AT_ALL_TF=True`` → off; ``False`` → on.
    Operator owns the constant (no in-process override).
    """
    try:
        import core.constants as _cc

        return not bool(getattr(_cc, "NO_GUI_AT_ALL_TF", False))
    except Exception:
        return True


def _project_root_for_assets() -> Path:
    """``gui/gui_constants.py`` → project root (parent of ``gui/``)."""
    return Path(__file__).resolve().parents[1]


def _sound_file_path(rel: str) -> Path:
    """Resolve sound path relative to project root (cwd-independent)."""
    p = Path(rel)
    if p.is_file():
        return p
    cand = _project_root_for_assets() / rel
    return cand

# Specs survive re-init: initialize_fonts() replaces Enum .value with Font dicts.
_FONT_SPECS = {
    "SMALL": ("Comic Sans MS", 10),
    "NORMAL": ("Comic Sans MS", 16),
    "LARGE": ("Comic Sans MS", 24),
}


class Font(Enum):
    """Enumeration for font sizes."""

    SMALL = ("Comic Sans MS", 10)
    NORMAL = ("Comic Sans MS", 16)
    LARGE = ("Comic Sans MS", 24)

    @classmethod
    def initialize_fonts(cls) -> None:
        """Initialize Pygame font module and create font objects with bold variants.

        Idempotent across ``pygame.quit()`` / re-init cycles: after the first call
        each member's ``.value`` is a ``{regular, bold}`` dict; later calls re-read
        name/size from ``_FONT_SPECS`` instead of unpacking that dict.
        """
        if not pygame.font.get_init():
            pygame.font.init()
        for font in cls:
            spec = _FONT_SPECS.get(font.name)
            if spec is not None:
                font_name, size = spec
            else:
                val = font.value
                if isinstance(val, dict):
                    # Fallback: already converted and missing from _FONT_SPECS
                    continue
                font_name, size = val
            font._value_ = {
                "regular": pygame.font.SysFont(font_name, int(size), bold=False),
                "bold": pygame.font.SysFont(font_name, int(size), bold=True),
            }

# class Font(Enum):
#     """Enumeration for font sizes."""
  
#     SMALL = ("Comic Sans MS", 10)
#     NORMAL = ("Comic Sans MS", 16)
#     LARGE = ("Comic Sans MS", 24)

#     @classmethod
#     def initialize_fonts(cls) -> None:
#         """Initialize Pygame font module and create font objects with bold variants."""
#         if not pygame.font.get_init():
#             pygame.font.init()
#         # Log all Font enum values before processing
#         if MG:
#             with open(FILENAME_MG, "a") as f:
#                 f.write(f"gui_constants.py | initialize_fonts | Font enum values before: {[f'{font.name}: {font.value}' for font in cls]}\n")
#         for font in cls:
#             print(f"Font {font.name}: {font.value} (before unpacking)")
#             font_name, size = font.value
#             print(f"Font {font.name}: font_name={font_name}, size={size}, type={type(size)} (after unpacking)")
#             if not isinstance(size, int):
#                 if MG:
#                     with open(FILENAME_MG, "a") as f:
#                         f.write(f"gui_constants.py | initialize_fonts | Invalid size type for font {font.name}: {type(size)}, value: {font.value}\n")
#                 raise TypeError(f"Font size for {font.name} must be an integer, got {type(size)}: {size}")
#             font._font_objects = {  # Store in a new attribute
#                 "regular": pygame.font.SysFont(font_name, size, bold=False),
#                 "bold": pygame.font.SysFont(font_name, size, bold=True)
#             }
#             print(f"Font {font.name}: _font_objects={font._font_objects}")
#         if MG:
#             with open(FILENAME_MG, "a") as f:
#                 f.write(f"gui_constants.py | initialize_fonts | Font enum values after: {[f'{font.name}: {font.value}' for font in cls]}\n")

class Color(Enum):
    """Enumeration for color values used in rendering."""
   
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    LGRAY = (200, 200, 200)
    DGRAY = (100, 100, 100)
    GRAY = (169, 169, 169)
    GREEN = (0, 255, 0)
    BLUE = (0, 0, 255)
    RED = (255, 0, 0)
    ORANGE = (255, 165, 0)
    FIELD = (255, 255, 153)
    MOUNTAIN = (139, 69, 19)
    FOREST = (0, 100, 0)
    HILL = (204, 0, 0)
    PASTURE = (173, 255, 47)
    DESERT = (245, 245, 220)
    SEA = (0, 191, 255)

COLORS: Dict[str, Tuple[int, int, int]] = {color.name: color.value for color in Color}
"""Dictionary mapping color names to RGB tuples for rendering."""

REVERSE_COLOR_MAPPING: Dict[str, str] = {
    "Blue": "Orange",
    "Red": "White",
    "White": "Red",
    "Orange": "Blue"
}
"""Dictionary mapping player colors to their opposites for game logic."""

class Sound(Enum):
    """Enumeration for sound effect file paths."""
   
    DICEROLL = "assets/sounds/DiceRoll.wav"
    BUTTON = "assets/sounds/button-click-3.wav"
    BUTTONHP = "assets/sounds/Bell2.wav"
    BUILDROAD = "assets/sounds/BuildRoad.wav"
    FANFARE = "assets/sounds/fanfare-2.wav"
    BELL = "assets/sounds/success-bell.wav"
    ERROR = "assets/sounds/Error-sound.wav"
    DANGER = "assets/sounds/Danger.wav"
    STEAL = "assets/sounds/CashRegister.wav"
    DEAL = "assets/sounds/CashRegister.wav"
    NOTWPFOUND = "assets/sounds/No_TwP_Found.wav"
    TWPFOUND = "assets/sounds/TwP_Found.wav"
    TWPFOUND2 = "assets/sounds/infobleep.wav"
    BUYDCARD = "assets/sounds/BuyDCard2.wav"
    PLAYDCARD = "assets/sounds/PlayDCard.wav"
    NEXTTURN = "assets/sounds/NoGui_NextTurn.wav"
    NEXTGAME = "assets/sounds/NoGui_NextGame.wav"
    MIDGAME = "assets/sounds/NoGui_Midgame.wav"
    ENDGAME = "assets/sounds/NoGui_Endgame.wav"

SOUNDS: Dict[str, pygame.mixer.Sound] = {}
"""Dictionary mapping sound effect names to Pygame Sound objects."""


def initialize_sounds(*, force: bool = False) -> int:
    """Initialize sound effects and populate the SOUNDS dictionary.

    No-op when ``NO_GUI_AT_ALL_TF=True`` (``force`` is ignored — operator owns
    the constant). Paths are resolved from the project root so loading does
    not depend on process cwd.

    Returns the number of successfully loaded sound objects.
    """
    _ = force  # kept for call-site compatibility; does not bypass NO_GUI
    if not is_audio_enabled():
        SOUNDS.clear()
        return 0
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
    except Exception:
        return 0
    loaded = 0
    for sound in Sound:
        path = _sound_file_path(str(sound.value))
        try:
            if not path.is_file():
                raise FileNotFoundError(str(path))
            SOUNDS[sound.name] = pygame.mixer.Sound(str(path))
            loaded += 1
        except Exception:
            SOUNDS[sound.name] = None
            if MG:
                try:
                    with open(FILENAME_MG, "a") as f:
                        f.write(
                            f"gui_constants.py | initialize_sounds | "
                            f"Missing/bad sound file: {path}\n"
                        )
                except Exception:
                    pass
    return loaded


def ensure_replay_audio() -> int:
    """Load sounds for interactive re-play after the display exists.

    Call after ``pygame.display.set_mode`` / importing ``WIN`` so the mixer is
    (re)initialized with a display present — needed on some Windows setups.
    Requires ``NO_GUI_AT_ALL_TF=False`` (same as ``is_audio_enabled``).
    """
    try:
        # Display may have been created after an earlier mixer.init(); re-init.
        try:
            if pygame.mixer.get_init():
                pygame.mixer.quit()
        except Exception:
            pass
        pygame.mixer.init()
    except Exception:
        pass
    return initialize_sounds()


def play_sound(name: str, fallback: str = "BUTTON") -> bool:
    """Play a named sound effect if audio is enabled and the asset exists.

    Preferred choke-point for all UI/core sound playback. Returns True when a
    sound was started; False when muted, missing, or on any error.
    """
    if not is_audio_enabled():
        return False
    key = str(name or "").strip()
    fb = str(fallback or "").strip()
    if not key and not fb:
        return False
    try:
        if not any(v is not None for v in SOUNDS.values()):
            initialize_sounds()
        sound = SOUNDS.get(key) if key else None
        if sound is None and fb:
            sound = SOUNDS.get(fb)
        if sound is None:
            # Lazy one-shot load of the requested key
            for candidate in (key, fb):
                if not candidate:
                    continue
                try:
                    rel = Sound[candidate].value
                except Exception:
                    continue
                path = _sound_file_path(str(rel))
                if path.is_file():
                    try:
                        sound = pygame.mixer.Sound(str(path))
                        SOUNDS[candidate] = sound
                        break
                    except Exception:
                        continue
        if sound is None:
            return False
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init()
            except Exception:
                return False
        play = getattr(sound, "play", None)
        if callable(play):
            play()
            return True
        pygame.mixer.Sound.play(sound)
        return True
    except Exception:
        return False

class Image(Enum):
    """Enumeration for image asset paths and sizes."""
   
    DICE_1 = ("assets/images/1.png", (75, 75))
    DICE_2 = ("assets/images/2.png", (75, 75))
    DICE_2B = ("assets/images/2b.png", (75, 75))
    DICE_3 = ("assets/images/3.png", (75, 75))
    DICE_3B = ("assets/images/3b.png", (75, 75))
    DICE_4 = ("assets/images/4.png", (75, 75))
    DICE_5 = ("assets/images/5.png", (75, 75))
    DICE_6 = ("assets/images/6.png", (75, 75))
    DICE_6B = ("assets/images/6b.png", (75, 75))
    MOUNTAIN = ("assets/images/Mountain3.png", [(40, 40), (20, 20)])
    FIELD = ("assets/images/Field2.png", [(40, 40), (20, 20)])
    FOREST = ("assets/images/Woods.png", [(40, 40), (20, 20)])
    HILL = ("assets/images/Hills3.png", [(40, 40), (20, 20)])
    PASTURE = ("assets/images/Grass.png", [(40, 40), (20, 20)])
    DESERT = ("assets/images/Desert.png", (40, 40))
    SEA = ("assets/images/Sea3.png", (40, 40))
    PLUS = ("assets/images/Plus.png", (50, 50))
    MIN = ("assets/images/Min.png", (50, 50))
    FINISH = ("assets/images/Finish2.png", (50, 50))
    ROBBER = ("assets/images/Robber.png", (40, 40))
    SETTINGS_ON = ("assets/images/Settings3.png", (40, 40))
    SETTINGS_OFF = ("assets/images/Settings.png", (40, 40))
    QUESTIONMARK = ("assets/images/Questionmark.png", (40, 40))
    DC_VPOINT = ("assets/images/vp.jpg", [(20, 20), (30, 30), (40, 40)])
    DC_KNIGHT = ("assets/images/knight.png", [(20, 20), (30, 30), (40, 40)])
    DC_ROAD = ("assets/images/road.jpg", [(20, 20), (30, 30), (40, 40)])
    DC_PLENTY = ("assets/images/plenty2.png", [(20, 20), (30, 30), (40, 40)])
    DC_MONOPOLY = ("assets/images/monopoly.png", [(20, 20), (30, 30), (40, 40)])
    OKY = ("assets/images/OK.png", (40, 40))
    OKN = ("assets/images/OK_pale.png", (40, 40))
    NOK = ("assets/images/NOK.png", (40, 40))
    CITY_BLUE = ("assets/images/CityBlue4s.png", [(30, 30), (40, 40)])
    SETTLEMENT_BLUE = ("assets/images/BarnBlue5s.png", [(30, 30), (40, 40)])
    CITY_RED = ("assets/images/CityRed4s.png", [(30, 30), (40, 40)])
    SETTLEMENT_RED = ("assets/images/BarnRed4s.png", [(30, 30), (40, 40)])
    CITY_WHITE = ("assets/images/CityWhite3s.png", [(30, 30), (40, 40)])
    SETTLEMENT_WHITE = ("assets/images/BarnWhite2s.png", [(30, 30), (40, 40)])
    CITY_ORANGE = ("assets/images/CityOrange4s.png", [(30, 30), (40, 40)])
    SETTLEMENT_ORANGE = ("assets/images/BarnOrange4s.png", [(30, 30), (40, 40)])
    CITY_GREEN = ("assets/images/CityGreen1s.png", [(40, 40), (30, 30)])
    SETTLEMENT_GREEN = ("assets/images/BarnGreen2s.png", [(40, 40), (30, 30)])
    CITY_DGRAY = ("assets/images/CityDGray1s.png", [(40, 40), (30, 30)])
    SETTLEMENT_DGRAY = ("assets/images/BarnDGray2s.png", [(40, 40), (30, 30)])
    ROAD_GREEN = ("assets/images/RoadGreen.png", [(40, 40), (30, 30)])
    ROAD_DGRAY = ("assets/images/RoadGray.png", [(40, 40), (30, 30)])
    DCARD_GREEN = ("assets/images/DCardGreen.png", [(40, 40), (30, 30)])
    DCARD_DGRAY = ("assets/images/DCardGray.png", [(40, 40), (30, 30)])
    TWP_GREEN = ("assets/images/TwPGreen.png", (40, 40))
    TWP_RED = ("assets/images/TwPRed.png", (40, 40))
    TWP_MODE_RED = ("assets/images/TwP_Red.png", (30, 30))
    TWP_MODE_AI = ("assets/images/TwP_AI.png", (30, 30))
    TWP_MODE_AUTO = ("assets/images/TwP_Auto.png", (30, 30))
    TWP_MODE_EDIT_AUTO = ("assets/images/Edit_TwP_Auto.png", (30, 30))

IMAGES: Dict[str, Dict[str, pygame.Surface]] = {}
"""Dictionary mapping image asset names to dictionaries of size keys (e.g., '40x40') and scaled Pygame Surfaces."""
for img in Image:
    try:
        path, sizes = img.value
        if isinstance(sizes, list):
            IMAGES[img.name] = {
                f"{size[0]}x{size[1]}": pygame.transform.scale(pygame.image.load(str(Path(path))), size)
                for size in sizes
            }
        else:
            IMAGES[img.name] = {"default": pygame.transform.scale(pygame.image.load(str(Path(path))), sizes)}
    except FileNotFoundError:
        IMAGES[img.name] = {f"{size[0]}x{size[1]}": None for size in sizes} if isinstance(sizes, list) else {"default": None}
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_constants.py | IMAGES | Missing image file: {path}\n")

WIN = pygame.display.set_mode((1225, 800))
"""Pygame display surface for rendering the game window."""

BOARD_OFFSET: Tuple[int, int] = (230, 50)
"""Tuple specifying the (x, y) offset for board elements."""

# ─────────────────────────────────────────────────────────────────────────────
# Canonical GUI panel layout map
# ─────────────────────────────────────────────────────────────────────────────
# Coordinate format is pygame.Rect(x, y, width, height). Keep large UI regions
# here instead of scattering magic numbers across gui.py. This gives peers one
# place to inspect screen real estate and helps prevent accidental overlap.
SCREEN_WIDTH, SCREEN_HEIGHT = WIN.get_size()
PANEL_GAP: int = 10
"""Minimum pixel gap between major non-overlapping panels."""

PLAYBOARD_RECT = pygame.Rect(180 + BOARD_OFFSET[0], 25, 480, 475)
"""Main playboard drawing area."""

RIGHT_PANEL_SHIFT_UP: int = 10
"""Pixels used to lift the right-side event/debug/trade panels."""

TWITTER_PANEL_RECT = pygame.Rect(
    PLAYBOARD_RECT.right + PANEL_GAP,
    PLAYBOARD_RECT.y - RIGHT_PANEL_SHIFT_UP,
    max(260, SCREEN_WIDTH - (PLAYBOARD_RECT.right + PANEL_GAP) - 25),
    180,
)
"""Top-right event feed, shifted 10 px up from the playboard top."""

EXECUTION_DEBUG_PANEL_RECT = pygame.Rect(
    TWITTER_PANEL_RECT.x,
    TWITTER_PANEL_RECT.bottom + PANEL_GAP,
    TWITTER_PANEL_RECT.width,
    max(120, PLAYBOARD_RECT.bottom - RIGHT_PANEL_SHIFT_UP - (TWITTER_PANEL_RECT.bottom + PANEL_GAP)),
)
"""Mid-right Execution Slice A/B debug panel, shifted 10 px up with fixed old bottom."""

TRADE_BANK_PANEL_RECT = pygame.Rect(
    EXECUTION_DEBUG_PANEL_RECT.x,
    EXECUTION_DEBUG_PANEL_RECT.bottom + PANEL_GAP,
    EXECUTION_DEBUG_PANEL_RECT.width,
    max(170, min(260, SCREEN_HEIGHT - (EXECUTION_DEBUG_PANEL_RECT.bottom + PANEL_GAP) - 25)),
)
"""Human Trade-with-Bank/TwP slot (canonical right-side modal rect)."""

DISCARD_PANEL_RECT = pygame.Rect(
    TRADE_BANK_PANEL_RECT.x,
    TRADE_BANK_PANEL_RECT.y,
    TRADE_BANK_PANEL_RECT.width,
    TRADE_BANK_PANEL_RECT.height,
)
"""Human discard panel: same screen slot as TwB/TwP (only one active)."""

PLAY_DCARD_PANEL_RECT = pygame.Rect(
    TRADE_BANK_PANEL_RECT.x,
    TRADE_BANK_PANEL_RECT.y,
    TRADE_BANK_PANEL_RECT.width,
    TRADE_BANK_PANEL_RECT.height,
)
"""Human Play DCard panel (Knight / TFR / YOP / Monopoly): same shared modal
slot as TwB/TwP/discard — one rect for all DCard types, body switches by type.
Only one of TwB / TwP / discard / play_dcard should be active at a time."""

GAME_OVER_PANEL_RECT = pygame.Rect(
    TRADE_BANK_PANEL_RECT.x,
    TRADE_BANK_PANEL_RECT.y,
    TRADE_BANK_PANEL_RECT.width,
    TRADE_BANK_PANEL_RECT.height,
)
"""Legacy alias for the shared right-side modal slot (TwB/TwP/discard).
S7a+ Statistics content uses STATISTICS_CANVAS_RECT (left stack), not this rect.
Kept for layout map / older screenshots references."""

# Playable development-card types (scoreboard / play panel). VP is never playable.
DCARD_PLAY_TYPES: tuple = (
    "victory_point",
    "knight",
    "two_free_roads",
    "year_of_plenty",
    "monopoly",
)
DCARD_PLAY_LABELS: dict = {
    "victory_point": "Victory Point",
    "knight": "Knight",
    "two_free_roads": "Two Free Roads",
    "year_of_plenty": "Year of Plenty",
    "monopoly": "Monopoly",
}
DCARD_PLAY_IMAGE_KEYS: dict = {
    "victory_point": "DC_VPOINT",
    "knight": "DC_KNIGHT",
    "two_free_roads": "DC_ROAD",
    "year_of_plenty": "DC_PLENTY",
    "monopoly": "DC_MONOPOLY",
}
# Scoreboard border colors for playable DCards
DCARD_PLAYABLE_BORDER = (0, 200, 0)  # green: can click
DCARD_PANEL_OPEN_BORDER = (255, 196, 0)  # gold: this type's panel is open

LEFT_DICE_PANEL_RECT = pygame.Rect(15, 370, 175, 90)
"""Left-side temporary dice display after an Execution dice roll."""

# ─────────────────────────────────────────────────────────────────────────────
# Top-left stack (must not overlap each other or TwP Mode icons at y≈215)
# ─────────────────────────────────────────────────────────────────────────────
# Vertical order:
#   1) Round / Turn   (LARGE font at y=5)     → ROUND_TURN_RECT
#   2) Human guidance  (raised under Round)   → GUIDANCE_TEXT_RECT
#   3) Resource Potential (lowered)           → RESOURCE_POTENTIAL_RECT
#   4) TwP Mode icons                         → HUMAN_BUTTON_ROW_Y["twp_mode"] ≈ 215–220
#
# Gaps (approx): Round ends ~34 | Guidance 36–78 | RP 86–181 | TwP 215+
ROUND_TURN_RECT = pygame.Rect(2, 2, 400, 32)
"""Clear/hit band for Round + Turn labels (blit at y=5, Font.LARGE ~24 px)."""

GUIDANCE_TEXT_RECT = pygame.Rect(10, 36, 420, 44)
"""Human placement/buy guidance strip under Round/Turn (raised vs old y≈45–85).
Holds up to ~2 normal-font lines; bottom y=80 — does not enter Round/Turn or RP."""

GUIDANCE_TEXT_LINE0_Y: int = 40
"""First guidance text baseline y (inside GUIDANCE_TEXT_RECT)."""

GUIDANCE_TEXT_LINE_SPACING: int = 18
"""Vertical step between guidance lines."""

RESOURCE_POTENTIAL_RECT = pygame.Rect(5, 86, 400, 95)
"""Resource Potential panel (lowered under guidance; bottom y=181).
Gap to TwP Mode icons (top ≈ 215): ~34 px — no overlap."""

RESOURCE_POTENTIAL_HEADER_Y: int = 94
RESOURCE_POTENTIAL_LABEL_Y: int = 116
RESOURCE_POTENTIAL_CURRENT_Y: int = 130
RESOURCE_POTENTIAL_APPROX_Y: int = 148
"""Row y positions inside RESOURCE_POTENTIAL_RECT (header / labels / current / remaining)."""

# ─────────────────────────────────────────────────────────────────────────────
# Human execution button panel
# ─────────────────────────────────────────────────────────────────────────────
# The original button panel bottom is kept at y=520.  The TwP Mode row lives
# above this border; the border starts between TwP Mode and Buy.  Top padding
# to Buy equals bottom padding under PLAY/CONTINUE: 10 px.
HUMAN_BUTTON_PANEL_RECT = pygame.Rect(10, 265, 330, 255)
"""Human action button panel excluding the compact TwP Mode row; bottom remains 520."""

HUMAN_BUTTON_ROW_Y = {
    "twp_mode": 220,
    "buy": 275,
    "trade": 330,
    "dice": 405,
    "play": 470,
}
"""Canonical y coordinates for the Human button panel rows.
TwP Mode icons top ≈ 215 (row y 220 − 5); stays below RESOURCE_POTENTIAL_RECT.bottom (181)."""

HUMAN_TWP_MODE_LABEL_POS = (25, HUMAN_BUTTON_ROW_Y["twp_mode"] + 4)
"""Text position for the TwP Mode label in the Human button panel."""

# TwP Mode icons are 30x30 images inside 40x40 clickable/bordered slots,
# matching the Buy button visual style: a compact image with a larger border.
# X coordinates intentionally match the 4 Buy buttons one row lower.
HUMAN_BUTTON_RECTS = {
    "twp_mode_red": pygame.Rect(140, HUMAN_BUTTON_ROW_Y["twp_mode"] - 5, 40, 40),
    "twp_mode_ai": pygame.Rect(190, HUMAN_BUTTON_ROW_Y["twp_mode"] - 5, 40, 40),
    "twp_mode_auto": pygame.Rect(240, HUMAN_BUTTON_ROW_Y["twp_mode"] - 5, 40, 40),
    "edit_twp_auto": pygame.Rect(290, HUMAN_BUTTON_ROW_Y["twp_mode"] - 5, 40, 40),
    "buy_city": pygame.Rect(140, HUMAN_BUTTON_ROW_Y["buy"], 40, 40),
    "buy_settlement": pygame.Rect(190, HUMAN_BUTTON_ROW_Y["buy"], 40, 40),
    "buy_road": pygame.Rect(240, HUMAN_BUTTON_ROW_Y["buy"], 40, 40),
    "buy_dcard": pygame.Rect(290, HUMAN_BUTTON_ROW_Y["buy"], 40, 40),
    "twp": pygame.Rect(200, HUMAN_BUTTON_ROW_Y["trade"], 60, 40),
    "twb": pygame.Rect(270, HUMAN_BUTTON_ROW_Y["trade"], 60, 40),
    "roll_dices": pygame.Rect(200, HUMAN_BUTTON_ROW_Y["dice"], 130, 40),
    "end_turn": pygame.Rect(200, HUMAN_BUTTON_ROW_Y["play"], 130, 40),
    "continue_ai": pygame.Rect(200, HUMAN_BUTTON_ROW_Y["play"], 130, 40),
    "cancel": pygame.Rect(200, HUMAN_BUTTON_ROW_Y["play"], 130, 40),
    "next_turn2": pygame.Rect(20, HUMAN_BUTTON_ROW_Y["play"], 130, 40),
}
"""Canonical clickable button rectangles for gui_human_player and event_handler."""

# ─────────────────────────────────────────────────────────────────────────────
# Scoreboard (lower band)
# ─────────────────────────────────────────────────────────────────────────────
# Height 200 (was 240): unused bottom 40 px removed so Settings gear can sit
# 40 px higher without overlapping scoreboard content. y still 540; bottom=740.
SCOREBOARD_RECT = pygame.Rect(110, 540, 770, 200)
"""Persistent lower scoreboard with current totals and red turn deltas.
Rect: (110, 540, 770, 200) → bottom edge y=740."""

# ─────────────────────────────────────────────────────────────────────────────
# Settings chrome (BS-1) — gear under scoreboard + mid-game End-game confirm
# ─────────────────────────────────────────────────────────────────────────────
# Layout (left → right on the strip under the scoreboard):
#   [ Settings gear 40×40 ]  [ "End current game?" prompt ]  [ Yes ]  [ No ]
# Drawn only after first PLAY that starts IP; Yes = session abort, No = dismiss.
SETTINGS_BUTTON_SIZE: int = 40
SETTINGS_BUTTON_GAP: int = 8
SETTINGS_CONFIRM_PROMPT_W: int = 170
SETTINGS_CONFIRM_BTN_W: int = 56

SETTINGS_BUTTON_RECT = pygame.Rect(
    int(SCOREBOARD_RECT.x),
    int(SCOREBOARD_RECT.bottom) + int(SETTINGS_BUTTON_GAP),
    int(SETTINGS_BUTTON_SIZE),
    int(SETTINGS_BUTTON_SIZE),
)
"""Always-visible Settings gear under the scoreboard (Settings3 when enabled).
Rect: (110, 748, 40, 40) — fully on-screen (screen height 800)."""


def settings_end_game_confirm_rects(
    gear_rect: "pygame.Rect | None" = None,
) -> Dict[str, "pygame.Rect"]:
    """Prompt + Yes/No rects immediately to the right of the Settings gear."""
    gear = gear_rect if gear_rect is not None else SETTINGS_BUTTON_RECT
    gap = int(SETTINGS_BUTTON_GAP)
    h = int(SETTINGS_BUTTON_SIZE)
    y = int(gear.y)
    prompt_w = int(SETTINGS_CONFIRM_PROMPT_W)
    btn_w = int(SETTINGS_CONFIRM_BTN_W)
    x0 = int(gear.right) + gap
    return {
        "prompt": pygame.Rect(x0, y, prompt_w, h),
        "yes": pygame.Rect(x0 + prompt_w + gap, y, btn_w, h),
        "no": pygame.Rect(x0 + prompt_w + gap + btn_w + gap, y, btn_w, h),
    }


SETTINGS_END_GAME_CONFIRM_RECTS: Dict[str, pygame.Rect] = settings_end_game_confirm_rects()
"""Named End-current-game confirm rects:
  prompt → (158, 748, 170, 40)  \"End current game?\" (no border)
  yes    → (336, 748, 56, 40)
  no     → (400, 748, 56, 40)
"""

SETTINGS_END_GAME_CONFIRM_STRIP_RECT = (
    SETTINGS_BUTTON_RECT.union(SETTINGS_END_GAME_CONFIRM_RECTS["prompt"])
    .union(SETTINGS_END_GAME_CONFIRM_RECTS["yes"])
    .union(SETTINGS_END_GAME_CONFIRM_RECTS["no"])
)
"""Union of gear + prompt + Yes + No (erase / hit strip under scoreboard)."""

# ─────────────────────────────────────────────────────────────────────────────
# Board Settings menu / sub-menus (BS-3…BS-6) — right column
# ─────────────────────────────────────────────────────────────────────────────
# Occupies the Events + Execution Debug + TwB/TwP right stack while open.
# Playboard stays at PLAYBOARD_RECT. Pages drawn in this same footprint:
#   menu   → "Settings Board" main list (Exit / Random / Load / Empty / Edit / CIBI)
#   load   → Load board file picker
#   editor → "Settings Empty Board" | "Settings Edit Board" tools + Save/Cancel
#   cibi   → CIBI metrics
_bs_bottom = max(
    int(TRADE_BANK_PANEL_RECT.bottom),
    int(EXECUTION_DEBUG_PANEL_RECT.bottom),
    int(PLAYBOARD_RECT.bottom),
    int(TWITTER_PANEL_RECT.y) + 420,
)
_bs_bottom = min(_bs_bottom, int(SCOREBOARD_RECT.y) - 8)
if _bs_bottom <= int(TWITTER_PANEL_RECT.y) + 200:
    _bs_bottom = int(TWITTER_PANEL_RECT.y) + 420

BOARD_SETTINGS_PANEL_RECT = pygame.Rect(
    int(TWITTER_PANEL_RECT.x),
    int(TWITTER_PANEL_RECT.y),
    int(TWITTER_PANEL_RECT.width),
    int(_bs_bottom) - int(TWITTER_PANEL_RECT.y),
)
"""Right-column Board Settings modal (menu, load, empty/edit tools, CIBI).
Same x/width as TWITTER_PANEL_RECT; top = Events top; bottom stops above
scoreboard (SCOREBOARD_RECT.y - 8). Typical: (900, 15, 300, 517)."""

# Alias names for UI_PANEL_LAYOUT readability (same rect object)
BOARD_SETTINGS_MENU_RECT = BOARD_SETTINGS_PANEL_RECT
"""Main menu page footprint (Settings Board)."""

BOARD_SETTINGS_LOAD_RECT = BOARD_SETTINGS_PANEL_RECT
"""Load-board file picker footprint."""

BOARD_SETTINGS_EDITOR_RECT = BOARD_SETTINGS_PANEL_RECT
"""Empty/Edit tools sub-menu footprint (Settings Empty/Edit Board)."""

BOARD_SETTINGS_CIBI_RECT = BOARD_SETTINGS_PANEL_RECT
"""CIBI metrics page footprint."""

# ─────────────────────────────────────────────────────────────────────────────
# Post-game panels (W3 + S7a)
# ─────────────────────────────────────────────────────────────────────────────
# After game_over:
#   * STATISTICS_CANVAS_RECT — dense multi-table Statistics body (left stack)
#   * POST_GAME_STRIP_RECT   — winner banner + Statistics | Playboard | New Game
#   * GAME_OVER_PANEL_RECT   — legacy right-slot alias (not used for S7a body)
#
# Must sit after PLAYBOARD_RECT, HUMAN_BUTTON_PANEL_RECT, and SCOREBOARD_RECT.

_STATS_UNION_RECTS = (PLAYBOARD_RECT, HUMAN_BUTTON_PANEL_RECT, SCOREBOARD_RECT)
STATISTICS_CANVAS_RECT = pygame.Rect(
    min(r.x for r in _STATS_UNION_RECTS),
    min(r.y for r in _STATS_UNION_RECTS),
    max(r.right for r in _STATS_UNION_RECTS) - min(r.x for r in _STATS_UNION_RECTS),
    max(r.bottom for r in _STATS_UNION_RECTS) - min(r.y for r in _STATS_UNION_RECTS),
)
"""Post-game Statistics full canvas (S7a / R19): covers human buttons, playboard,
and scoreboard so multi-table stats fit. Drawn under the post-game strip."""

# G8 (28 Jul): post-game strip lives in the **right** TwB/TwP modal slot so it
# never overlaps the left Statistics canvas.
POST_GAME_STRIP_RECT = pygame.Rect(
    GAME_OVER_PANEL_RECT.x,
    GAME_OVER_PANEL_RECT.y,
    GAME_OVER_PANEL_RECT.width,
    GAME_OVER_PANEL_RECT.height,
)
"""Post-game control strip (winner banner + Statistics | Playboard | New Game).
Uses the shared right-side modal footprint (same as TwB/TwP)."""

# Strip button geometry (Statistics | Playboard | New Game) + New Game confirm
POST_GAME_STRIP_BUTTON_PAD: int = 10
POST_GAME_STRIP_BUTTON_GAP: int = 8
POST_GAME_STRIP_BUTTON_HEIGHT: int = 36
POST_GAME_STRIP_BUTTON_BOTTOM_MARGIN: int = 12


def post_game_strip_button_rects(
    strip_rect: "pygame.Rect | None" = None,
) -> Dict[str, "pygame.Rect"]:
    """Return the three post-game strip button rects (statistics / playboard / new_game)."""
    panel = strip_rect if strip_rect is not None else POST_GAME_STRIP_RECT
    pad = int(POST_GAME_STRIP_BUTTON_PAD)
    gap = int(POST_GAME_STRIP_BUTTON_GAP)
    h = int(POST_GAME_STRIP_BUTTON_HEIGHT)
    y = int(panel.bottom) - h - int(POST_GAME_STRIP_BUTTON_BOTTOM_MARGIN)
    inner_w = int(panel.width) - 2 * pad
    bw = max(70, (inner_w - 2 * gap) // 3)
    x0 = int(panel.x) + pad
    return {
        "statistics": pygame.Rect(x0, y, bw, h),
        "playboard": pygame.Rect(x0 + bw + gap, y, bw, h),
        "new_game": pygame.Rect(x0 + 2 * (bw + gap), y, bw, h),
    }


def post_game_confirm_new_game_rects(
    strip_rect: "pygame.Rect | None" = None,
) -> Dict[str, "pygame.Rect"]:
    """OKY / NOK-style confirm buttons for New Game (G8)."""
    panel = strip_rect if strip_rect is not None else POST_GAME_STRIP_RECT
    pad = int(POST_GAME_STRIP_BUTTON_PAD)
    gap = int(POST_GAME_STRIP_BUTTON_GAP)
    h = int(POST_GAME_STRIP_BUTTON_HEIGHT)
    y = int(panel.bottom) - h - int(POST_GAME_STRIP_BUTTON_BOTTOM_MARGIN)
    bw = max(90, (int(panel.width) - 2 * pad - gap) // 2)
    x0 = int(panel.x) + pad
    return {
        "confirm_ok": pygame.Rect(x0, y, bw, h),
        "confirm_cancel": pygame.Rect(x0 + bw + gap, y, bw, h),
    }


# Eager snapshot for layout maps / Phase0 (same values as post_game_strip_button_rects()).
POST_GAME_STRIP_BUTTON_RECTS: Dict[str, pygame.Rect] = post_game_strip_button_rects()
"""Named strip button rects: statistics, playboard, new_game."""

# Shared right-side modal aliases that were previously only documented in notes
TWP_AUTO_RULES_PANEL_RECT = pygame.Rect(
    TRADE_BANK_PANEL_RECT.x,
    TRADE_BANK_PANEL_RECT.y,
    TRADE_BANK_PANEL_RECT.width,
    TRADE_BANK_PANEL_RECT.height,
)
"""TwP Auto Rules editor: same shared right-side modal slot as TwB/TwP."""

TRADE_PLAYER_INCOMING_PANEL_RECT = pygame.Rect(
    TRADE_BANK_PANEL_RECT.x,
    TRADE_BANK_PANEL_RECT.y,
    TRADE_BANK_PANEL_RECT.width,
    TRADE_BANK_PANEL_RECT.height,
)
"""Incoming AI→HP TwP offer panel: same shared right-side modal slot as TwB/TwP."""

# ─────────────────────────────────────────────────────────────────────────────
# Scoreboard sub-layout
# ─────────────────────────────────────────────────────────────────────────────
# Keep all scoreboard sub-panel coordinates here instead of scattering magic
# numbers across gui.py. The question-mark buttons are centered between the
# resource-card dashboard and development-card statistic separators. The
# popup aligns with the left edge of victory_point.png.
SCOREBOARD_HEADER_X_POSITIONS = [115, 145, 165, 185, 205, 225, 245, 270, 300, 330, 360, 390, 435, 480, 525, 570]
"""X positions for the compact scoreboard total columns."""

RESOURCE_CARD_X_POSITIONS = [390, 435, 480, 525, 570]
"""Left x positions of the five 40x40 resource-card dashboard icons."""

DCARD_X_POSITIONS = [655, 690, 725, 760, 795]
"""Left x positions of the five 30x30 development-card statistic icons."""

SCOREBOARD_VERTICAL_LINES = {
    "before_resource_dashboard": 385,
    "after_resource_dashboard": 615,
    "before_turn_detail_buttons": 615,
    "before_dcard_statistics": 650,
}
"""Named vertical separator x-coordinates inside the scoreboard."""

SCOREBOARD_TOTALS_PANEL_RECT = pygame.Rect(110, 540, 275, 240)
"""Left compact totals area: VP, C, S, R, A, LR, LA, RC, DC."""

RESOURCE_DASHBOARD_RECT = pygame.Rect(385, 540, 230, 240)
"""Resource-card dashboard with current resource counts and red RCΔ deltas."""

TURN_DETAIL_BUTTON_COLUMN_RECT = pygame.Rect(
    SCOREBOARD_VERTICAL_LINES["after_resource_dashboard"],
    540,
    SCOREBOARD_VERTICAL_LINES["before_dcard_statistics"] - SCOREBOARD_VERTICAL_LINES["after_resource_dashboard"],
    240,
)
"""Narrow column between the resource dashboard and DCard statistics separators."""

DCARD_STATISTICS_PANEL_RECT = pygame.Rect(
    SCOREBOARD_VERTICAL_LINES["before_dcard_statistics"],
    540,
    SCOREBOARD_RECT.right - SCOREBOARD_VERTICAL_LINES["before_dcard_statistics"],
    240,
)
"""Development-card statistics area to the right of the '?' column."""

TURN_DETAIL_BUTTON_SIZE: int = 20
"""Pixel size of the per-player '?' turn-detail buttons."""

TURN_DETAIL_BUTTON_X: int = (
    SCOREBOARD_VERTICAL_LINES["after_resource_dashboard"]
    + SCOREBOARD_VERTICAL_LINES["before_dcard_statistics"]
    - TURN_DETAIL_BUTTON_SIZE
) // 2
"""Left x-position of the '?' buttons, centered between the two separator lines."""

TURN_DETAIL_POPUP_X: int = TWITTER_PANEL_RECT.x
"""Left x-position of the turn-detail popup; aligned with Twitter/Execution Debug panels."""

TURN_DETAIL_POPUP_RIGHT: int = TWITTER_PANEL_RECT.right
"""Right x-position of the turn-detail popup; aligned with Twitter/Execution Debug panels."""

TURN_DETAIL_PANEL_RECT = pygame.Rect(
    TURN_DETAIL_POPUP_X,
    585,
    TURN_DETAIL_POPUP_RIGHT - TURN_DETAIL_POPUP_X,
    165,
)
"""Turn-detail popup aligned with the development-card statistics panel."""

RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS: int = 60
"""Radius of the green tile highlight shown after resource production."""

RESOURCE_PRODUCTION_HIGHLIGHT_WIDTH: int = 2
"""Line width of the resource-production tile highlight circle."""

RESOURCE_PRODUCTION_HIGHLIGHT_DELAY_MS: int = 25
"""Frame delay for the v045-inspired resource-production tile reveal."""

# Robber / steal visual feedback constants. These mirror v045 look-and-feel:
# robber tile: white radius-60 tile ring; steal victim: red radius-20 intersection ring.
ROBBER_TILE_HIGHLIGHT_RADIUS: int = 60
"""Radius of the white tile highlight shown around the robber tile."""

VICTIM_STEAL_HIGHLIGHT_RADIUS: int = 20
"""Radius of the red intersection highlight shown around the robbed player's building(s)."""

ROBBER_AVAILABLE_TILE_HIGHLIGHT_RADIUS: int = 35
"""Radius of player-colored circles for legal human robber-tile choices."""

ROBBER_AVAILABLE_STEAL_TARGET_RADIUS: int = 20
"""Radius of player-colored circles for human steal-target choices."""

DCARD_HEADER_PLAY_PULSE_RADIUS: int = 24
"""Pulse radius around the shared scoreboard DCard header icon after a play (full seat-turn)."""

DCARD_HEADER_ICON_CENTER_Y: int = 560
"""Y-center of the shared DCard header 30x30 icons (must match update_scoreboard blit)."""

# Keep this intentionally unannotated. Some pygame type stubs expose
# pygame.Rect as a factory rather than a type, which can make VS Code/Pylance
# mark the next function definition red even though Python can run the file.
#
# COMPLETE list of major GUI / scoreboard / post-game panel rectangles.
# When adding a panel: define *_RECT above, then register it here + notes.
UI_PANEL_LAYOUT = {
    # ── Board & chrome ───────────────────────────────────────────────────
    "playboard": PLAYBOARD_RECT,
    "left_dice": LEFT_DICE_PANEL_RECT,
    "round_turn": ROUND_TURN_RECT,
    "guidance_text": GUIDANCE_TEXT_RECT,
    "resource_potential": RESOURCE_POTENTIAL_RECT,
    "human_buttons": HUMAN_BUTTON_PANEL_RECT,
    # ── Right column ─────────────────────────────────────────────────────
    "twitter_events": TWITTER_PANEL_RECT,
    "execution_debug": EXECUTION_DEBUG_PANEL_RECT,
    # ── Shared right-side modal slot (only one active at a time) ──────────
    "trade_bank": TRADE_BANK_PANEL_RECT,
    "trade_player": TRADE_BANK_PANEL_RECT,  # TwP outgoing
    "trade_player_incoming": TRADE_PLAYER_INCOMING_PANEL_RECT,  # AI→HP offer
    "discard": DISCARD_PANEL_RECT,
    "play_dcard": PLAY_DCARD_PANEL_RECT,
    "twp_auto_rules": TWP_AUTO_RULES_PANEL_RECT,
    "game_over": GAME_OVER_PANEL_RECT,  # legacy right-slot alias
    # ── Post-game (W3 + S7a + G8 right strip) ────────────────────────────
    "statistics_canvas": STATISTICS_CANVAS_RECT,  # full left-stack Statistics body
    "post_game_strip": POST_GAME_STRIP_RECT,  # right slot: winner + toggle buttons
    "post_game_strip_statistics": POST_GAME_STRIP_BUTTON_RECTS["statistics"],
    "post_game_strip_playboard": POST_GAME_STRIP_BUTTON_RECTS["playboard"],
    "post_game_strip_new_game": POST_GAME_STRIP_BUTTON_RECTS["new_game"],
    # ── Scoreboard (lower band + sub-panels) ─────────────────────────────
    "scoreboard": SCOREBOARD_RECT,
    "scoreboard_totals": SCOREBOARD_TOTALS_PANEL_RECT,
    "resource_dashboard": RESOURCE_DASHBOARD_RECT,
    "turn_detail_buttons": TURN_DETAIL_BUTTON_COLUMN_RECT,
    "dcard_statistics": DCARD_STATISTICS_PANEL_RECT,
    "turn_detail_popup": TURN_DETAIL_PANEL_RECT,
    # ── Settings chrome under scoreboard (BS-1) ──────────────────────────
    "settings_button": SETTINGS_BUTTON_RECT,
    "settings_confirm_strip": SETTINGS_END_GAME_CONFIRM_STRIP_RECT,
    "settings_confirm_prompt": SETTINGS_END_GAME_CONFIRM_RECTS["prompt"],
    "settings_confirm_yes": SETTINGS_END_GAME_CONFIRM_RECTS["yes"],
    "settings_confirm_no": SETTINGS_END_GAME_CONFIRM_RECTS["no"],
    # ── Board Settings menu / sub-menus (BS-3…BS-6) — right column ───────
    "board_settings": BOARD_SETTINGS_PANEL_RECT,
    "board_settings_menu": BOARD_SETTINGS_MENU_RECT,
    "board_settings_load": BOARD_SETTINGS_LOAD_RECT,
    "board_settings_editor": BOARD_SETTINGS_EDITOR_RECT,
    "board_settings_cibi": BOARD_SETTINGS_CIBI_RECT,
}
"""Named major GUI rectangles — single source of panel-layout truth.

Includes board chrome, right column, shared right modal family, post-game
Statistics canvas + strip, scoreboard (height 200), Settings gear + End-game
confirm strip, and Board Settings right-column menu/sub-menus.
"""

UI_PANEL_LAYOUT_NOTES = """
Catan GUI panel layout overview (complete UI_PANEL_LAYOUT keys)
--------------------------------------------------------------
Screen: 1225 × 800 (WIN).

Board & chrome
- playboard: main board drawing area (410, 25, 480, 475).
- left_dice: temporary dice display after an Execution roll.
- round_turn: Round + Turn labels top-left (2, 2, 400, 32); LARGE font at y=5.
- guidance_text: human guidance under Round/Turn (10, 36, 420, 44); raised so it
  no longer collides with Resource Potential.
- resource_potential: pip summary (5, 86, 400, 95); lowered under guidance,
  bottom y=181 — clears TwP Mode icons (top ≈ 215) by ~34 px.
- human_buttons: left action/control panel (TwP Mode + Buy/Trade/Dice/Play).

Right column (play-time)
- twitter_events: top-right event feed (900, 15, 300, 180).
- execution_debug: mid-right Slice A/B debug (900, 205, 300, 285).

Shared right-side modal slot (one footprint — only one of these active at a time):
  trade_bank              → TRADE_BANK_PANEL_RECT          (TwB)  ~ (900, 500, 300, 260)
  trade_player            → same rect                      (TwP outgoing)
  trade_player_incoming   → TRADE_PLAYER_INCOMING_PANEL_RECT (AI→HP offer)
  discard                 → DISCARD_PANEL_RECT
  play_dcard              → PLAY_DCARD_PANEL_RECT          (Knight/TFR/YOP/Monopoly)
  twp_auto_rules          → TWP_AUTO_RULES_PANEL_RECT
  game_over               → GAME_OVER_PANEL_RECT           (legacy right alias only)

Post-game (W3 + S7a) — after game_over:
  statistics_canvas       → STATISTICS_CANVAS_RECT
      Full left stack (human buttons ∪ playboard ∪ scoreboard). Multi-table stats body.
  post_game_strip         → POST_GAME_STRIP_RECT
      Right modal slot; winner banner + three green-border toggles.
  post_game_strip_statistics / _playboard / _new_game
      → POST_GAME_STRIP_BUTTON_RECTS[…] individual click targets.

Scoreboard band (resized for Settings gear)
- scoreboard: (110, 540, 770, 200) — height reduced from 240 → 200 so gear sits
  40 px higher; bottom edge y=740 (was 780).
- scoreboard_totals / resource_dashboard / turn_detail_buttons /
  dcard_statistics / turn_detail_popup: sub-panels inside the scoreboard band
  (see SCOREBOARD_* definitions above).

Settings chrome under scoreboard (BS-1)
- settings_button: SETTINGS_BUTTON_RECT (110, 748, 40, 40)
      Always visible. Enabled unless Game Over / confirm open / Board Settings open.
      Pre-first-PLAY → opens Board Settings menu.
      Post-first-PLAY → shows End-game confirm strip.
- settings_confirm_strip: SETTINGS_END_GAME_CONFIRM_STRIP_RECT
      Union of gear + prompt + Yes + No (erase region when confirm dismisses).
- settings_confirm_prompt: (158, 748, 170, 40)  text "End current game?" (no border)
- settings_confirm_yes:    (336, 748, 56, 40)
- settings_confirm_no:     (400, 748, 56, 40)
      No → dismiss strip, re-enable gear. Yes → session abort / fresh boot.

Board Settings menu / sub-menus (BS-3…BS-6) — right column
  All pages share BOARD_SETTINGS_PANEL_RECT ≈ (900, 15, 300, 517):
  top/width align with Events; bottom stops at SCOREBOARD_RECT.y - 8 (532).
  Playboard stays visible at PLAYBOARD_RECT. Human buttons hidden while open.

  board_settings / board_settings_menu
      "Settings Board" main list:
        1 Exit and use the playboard to play
        2 Random board
        3 Load board
        4 Empty board
        5 Edit board
        6 CIBI
  board_settings_load
      Load-board file list (Playboard_*.txt).
  board_settings_editor
      "Settings Empty Board" or "Settings Edit Board":
        Terrain / Number / Port tools + Save board / Cancel
        (same right footprint; playboard paint clicks on PLAYBOARD_RECT).
  board_settings_cibi
      CIBI Index + six metrics + footnote.

While Board Settings is open:
  - twitter_events / execution_debug / trade_bank are not drawn (slot reused).
  - human_buttons (TwP Mode + Buy/…) are not drawn.

Play DCard uses one shared panel shell (not a separate rect per DCard type).

When adding a new panel:
  1. Define *_RECT (or button map) in this file near related panels.
  2. Register it in UI_PANEL_LAYOUT.
  3. Document it in UI_PANEL_LAYOUT_NOTES.
  4. Draw/click code must reference the named rect (no magic numbers).
"""

def _rect_to_tuple(rect):
    """Return a pygame.Rect-like object as (x, y, width, height)."""
    return (int(rect.x), int(rect.y), int(rect.width), int(rect.height))


def panel_layout_overview():
    """Return major GUI panel rectangles as simple tuples for debug/inspection."""
    return {name: _rect_to_tuple(rect) for name, rect in UI_PANEL_LAYOUT.items()}


PANEL_OFFSET: Tuple[int, int] = (870, 240)
"""Tuple specifying the (x, y) offset for panel elements."""

PANEL_OFFSET_Y2: int = 900
"""Y-offset for secondary panel elements."""

POSITIONS: Dict[str, Union[Dict[int, Tuple[int, int]], Tuple[int, int, int, int]]] = {
    "intersections": {
        3: [280 + BOARD_OFFSET[0], 98],
        4: [320 + BOARD_OFFSET[0], 70],
        5: [360 + BOARD_OFFSET[0], 98],
        6: [400 + BOARD_OFFSET[0], 70],
        7: [440 + BOARD_OFFSET[0], 98],
        8: [480 + BOARD_OFFSET[0], 70],
        9: [520 + BOARD_OFFSET[0], 98],
        13: [240 + BOARD_OFFSET[0], 170],
        14: [280 + BOARD_OFFSET[0], 142],
        15: [320 + BOARD_OFFSET[0], 170],
        16: [360 + BOARD_OFFSET[0], 142],
        17: [400 + BOARD_OFFSET[0], 170],
        18: [440 + BOARD_OFFSET[0], 142],
        19: [480 + BOARD_OFFSET[0], 170],
        20: [520 + BOARD_OFFSET[0], 142],
        21: [560 + BOARD_OFFSET[0], 170],
        23: [200 + BOARD_OFFSET[0], 242],
        24: [240 + BOARD_OFFSET[0], 214],
        25: [280 + BOARD_OFFSET[0], 242],
        26: [320 + BOARD_OFFSET[0], 214],
        27: [360 + BOARD_OFFSET[0], 242],
        28: [400 + BOARD_OFFSET[0], 214],
        29: [440 + BOARD_OFFSET[0], 242],
        30: [480 + BOARD_OFFSET[0], 214],
        31: [520 + BOARD_OFFSET[0], 242],
        32: [560 + BOARD_OFFSET[0], 214],
        33: [600 + BOARD_OFFSET[0], 242],
        34: [200 + BOARD_OFFSET[0], 286],
        35: [240 + BOARD_OFFSET[0], 314],
        36: [280 + BOARD_OFFSET[0], 286],
        37: [320 + BOARD_OFFSET[0], 314],
        38: [360 + BOARD_OFFSET[0], 286],
        39: [400 + BOARD_OFFSET[0], 314],
        40: [440 + BOARD_OFFSET[0], 286],
        41: [480 + BOARD_OFFSET[0], 314],
        42: [520 + BOARD_OFFSET[0], 286],
        43: [560 + BOARD_OFFSET[0], 314],
        44: [600 + BOARD_OFFSET[0], 286],
        46: [240 + BOARD_OFFSET[0], 358],
        47: [280 + BOARD_OFFSET[0], 386],
        48: [320 + BOARD_OFFSET[0], 358],
        49: [360 + BOARD_OFFSET[0], 386],
        50: [400 + BOARD_OFFSET[0], 358],
        51: [440 + BOARD_OFFSET[0], 386],
        52: [480 + BOARD_OFFSET[0], 358],
        53: [520 + BOARD_OFFSET[0], 386],
        54: [560 + BOARD_OFFSET[0], 358],
        58: [280 + BOARD_OFFSET[0], 430],
        59: [320 + BOARD_OFFSET[0], 458],
        60: [360 + BOARD_OFFSET[0], 430],
        61: [400 + BOARD_OFFSET[0], 458],
        62: [440 + BOARD_OFFSET[0], 430],
        63: [480 + BOARD_OFFSET[0], 458],
        64: [520 + BOARD_OFFSET[0], 430],
    },
    "tiles": {
        2: [280 + BOARD_OFFSET[0], 48],
        3: [360 + BOARD_OFFSET[0], 48],
        4: [440 + BOARD_OFFSET[0], 48],
        5: [520 + BOARD_OFFSET[0], 48],
        8: [240 + BOARD_OFFSET[0], 120],
        9: [320 + BOARD_OFFSET[0], 120],
        10: [400 + BOARD_OFFSET[0], 120],
        11: [480 + BOARD_OFFSET[0], 120],
        12: [560 + BOARD_OFFSET[0], 120],
        14: [200 + BOARD_OFFSET[0], 192],
        15: [280 + BOARD_OFFSET[0], 192],
        16: [360 + BOARD_OFFSET[0], 192],
        17: [440 + BOARD_OFFSET[0], 192],
        18: [520 + BOARD_OFFSET[0], 192],
        19: [600 + BOARD_OFFSET[0], 192],
        20: [160 + BOARD_OFFSET[0], 264],
        21: [240 + BOARD_OFFSET[0], 264],
        22: [320 + BOARD_OFFSET[0], 264],
        23: [400 + BOARD_OFFSET[0], 264],
        24: [480 + BOARD_OFFSET[0], 264],
        25: [560 + BOARD_OFFSET[0], 264],
        26: [640 + BOARD_OFFSET[0], 264],
        27: [200 + BOARD_OFFSET[0], 336],
        28: [280 + BOARD_OFFSET[0], 336],
        29: [360 + BOARD_OFFSET[0], 336],
        30: [440 + BOARD_OFFSET[0], 336],
        31: [520 + BOARD_OFFSET[0], 336],
        32: [600 + BOARD_OFFSET[0], 336],
        34: [240 + BOARD_OFFSET[0], 408],
        35: [320 + BOARD_OFFSET[0], 408],
        36: [400 + BOARD_OFFSET[0], 408],
        37: [480 + BOARD_OFFSET[0], 408],
        38: [560 + BOARD_OFFSET[0], 408],
        41: [280 + BOARD_OFFSET[0], 480],
        42: [360 + BOARD_OFFSET[0], 480],
        43: [440 + BOARD_OFFSET[0], 480],
        44: [520 + BOARD_OFFSET[0], 480],
    },
    "buttons": {
        **{name: _rect_to_tuple(rect) for name, rect in HUMAN_BUTTON_RECTS.items()},
        "analysis": (1040, 668, 130, 40),
        "new_game": (900, 668, 130, 40),
        "quit": (1040, 668, 130, 40)
    },
    "panels": {
        "discard_rcards": (10 + PANEL_OFFSET[0], 205 + PANEL_OFFSET[1], 250, 340),
        "twp_panel": (10 + PANEL_OFFSET[0], 205 + PANEL_OFFSET[1], 296, 340),
        "hp_buttons": _rect_to_tuple(HUMAN_BUTTON_PANEL_RECT),
    }
}
"""Dictionary mapping element types (intersections, tiles, buttons, panels) to their positions as (x, y) or (x, y, width, height) tuples."""
