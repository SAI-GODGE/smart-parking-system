"""Process-wide lock used to serialise parking state changes.

The application runs as a single Flask process against SQLite. Guarding
allocate / check-in / checkout / cancel with one lock guarantees that two
simultaneous requests can never both pass an availability check and then
write conflicting reservations for the same bay. Every state change also
re-reads the database inside the lock, so decisions are always made against
fresh data.
"""

import threading

BOOKING_LOCK = threading.RLock()
