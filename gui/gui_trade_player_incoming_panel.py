"""Compatibility wrapper for the Step 3 incoming AI→HP TwP panel.

The clean architecture moved incoming-panel drawing/click handling into
``gui.gui_trade_player_panel`` so outgoing and incoming TwP panels share one
layout source.  This wrapper is kept only so older imports do not break.
"""

from gui.gui_trade_player_panel import (
    close_incoming_twp_panel,
    draw_incoming_twp_panel,
    handle_incoming_twp_panel_click,
    is_incoming_twp_panel_active,
    open_incoming_twp_panel,
)
