"""HomeKit-Schloss, das immer „verriegelt“ bleibt.

kormax' Lock schaltet bei jedem erkannten Home Key um – die Home-App meldet dann
„aufgesperrt“. Das Schloss dient hier nur dazu, den Home Key ins Wallet zu bringen.
"""

from collections.abc import Callable

from .kormax import Lock

SECURED = 1


class QuietLock(Lock):
    def __init__(self, driver, name, *, service, on_homekey: Callable[[object], None]) -> None:
        super().__init__(driver, name, service=service, lock_state_at_startup=SECURED)
        # Ersetzt Lock.on_endpoint_authenticated (das umschalten würde).
        service.on_endpoint_authenticated = on_homekey

    def set_lock_target_state(self, value):
        """„Aufschließen“ aus Home-App/Siri/Automation: sofort zurück auf verriegelt."""
        self._lock_target_state = self._lock_current_state = SECURED
        self.lock_target_state.set_value(SECURED, should_notify=True)
        self.lock_current_state.set_value(SECURED, should_notify=True)
        return SECURED
