"""Keeps WebSocket subscriptions equal to the desired set: subscribes new, unsubscribes removed, no duplicates."""
import threading


class SubscriptionManager:
    def __init__(self, feed):
        self.feed = feed; self.cur = set(); self.lk = threading.Lock()

    def sync(self, desired):
        with self.lk:
            add, rem = desired - self.cur, self.cur - desired
            if rem: self.feed.unsubscribe(list(rem))
            if add: self.feed.subscribe(sorted(add))
            self.cur = set(desired)
            return len(add), len(rem)

    def reset(self):
        with self.lk: self.cur = set()
