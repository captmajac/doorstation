"""HomeKit lock that always stays "secured".

kormax' Lock toggles on every recognized Home Key - the Home app then reports
"unlocked". Here the lock only serves to get the Home Key into the Wallet.
"""

from collections.abc import Callable

from .kormax import Lock

SECURED = 1


class QuietLock(Lock):
    def __init__(self, driver, name, *, service, on_homekey: Callable[[object], None]) -> None:
        super().__init__(driver, name, service=service, lock_state_at_startup=SECURED)
        # Replaces Lock.on_endpoint_authenticated (which would toggle).
        service.on_endpoint_authenticated = on_homekey

    def set_lock_target_state(self, value):
        """"Unlock" from the Home app/Siri/automation: immediately back to secured."""
        self._lock_target_state = self._lock_current_state = SECURED
        self.lock_target_state.set_value(SECURED, should_notify=True)
        self.lock_current_state.set_value(SECURED, should_notify=True)
        return SECURED
