import uuid
from typing import Callable, Optional, Dict, Protocol

from testplan.event_stream.events import Event
from testplan.event_stream.filter import EventFilter

EventCallback = Callable[[str, Event], None]


class Subscription:
    def __init__(
        self,
        topic: str,
        callback: EventCallback,
        event_filter: Optional[EventFilter] = None,
    ):
        self.topic = topic
        self.callback = callback
        self.event_filter = event_filter


class TopicProcessor(Protocol):
    def register_subscription(self, subscription: Subscription) -> None:
        ...

    def remove_subscription(self, subscription: Subscription) -> None:
        ...

    def process(self, event: Event) -> None:
        ...


class SyncTopicProcessor(TopicProcessor):
    def __init__(self, topic: str):
        self.topic = topic
        self.subscriptions = []

    def register_subscription(self, subscription: Subscription) -> None:
        self.subscriptions.append(subscription)

    def remove_subscription(self, subscription: Subscription) -> None:
        self.subscriptions.remove(subscription)

    def process(self, event: Event) -> None:
        for subscription in self.subscriptions:
            # TODO: add event filtering
            subscription.callback(self.topic, event)


class Aggregator:
    def __init__(self):
        self.subscriptions: Dict[uuid.UUID, Subscription] = {}
        self.processors: Dict[str, TopicProcessor] = {}

    def publish(self, topic: str, event: Event):
        if topic not in self.processors:
            return
        self.processors[topic].process(event)

    def subscribe(
        self,
        topic: str,
        callback: EventCallback,
        event_filter: Optional[EventFilter] = None,
    ) -> uuid.UUID:

        subscription = Subscription(topic, callback, event_filter)
        subscription_id = uuid.uuid4()

        self.subscriptions[subscription_id] = subscription
        self.register_subscription(subscription)
        return subscription_id

    def register_subscription(self, subscription):
        topic = subscription.topic
        if topic not in self.processors:
            self.processors[topic] = SyncTopicProcessor(topic)

        self.processors[topic].register_subscription(subscription)
