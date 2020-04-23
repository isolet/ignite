from typing import Callable, Optional, Union, Any

from enum import Enum
import numbers
import weakref
from types import DynamicClassAttribute

from ignite.engine.utils import _check_signature

__all__ = ["Events", "State"]


class CallableEventWithFilter:
    """Single Event containing a filter, specifying whether the event should
    be run at the current event (if the event type is correct)

    Args:
        value (str): The actual enum value. Only needed for internal use. Do not touch!
        event_filter (callable): A function taking the engine and the current event value as input and returning a
            boolean to indicate whether this event should be executed. Defaults to None, which will result to a
            function that always returns `True`
        name (str, optional): The enum-name of the current object. Only needed for internal use. Do not touch!

    """

    def __init__(self, value: str, event_filter: Optional[Callable] = None, name=None):
        if event_filter is None:
            event_filter = CallableEventWithFilter.default_event_filter
        self.filter = event_filter

        if not hasattr(self, "_value_"):
            self._value_ = value

        if not hasattr(self, "_name_") and name is not None:
            self._name_ = name

    # copied to be compatible to enum
    @DynamicClassAttribute
    def name(self):
        """The name of the Enum member."""
        return self._name_

    @DynamicClassAttribute
    def value(self):
        """The value of the Enum member."""
        return self._value_

    def __call__(
        self, event_filter: Optional[Callable] = None, every: Optional[int] = None, once: Optional[int] = None
    ) -> "CallableEventWithFilter":
        """
        Makes the event class callable and accepts either an arbitrary callable as filter
        (which must take in the engine and current event value and return a boolean) or an every or once value

        Args:
            event_filter (callable, optional): a filter function to check if the event should be executed when
                the event type was fired
            every (int, optional): a value specifying how often the event should be fired
            once (int, optional): a value specifying when the event should be fired (if only once)

        Returns:
            CallableEventWithFilter: A new event having the same value but a different filter function
        """

        if not ((event_filter is not None) ^ (every is not None) ^ (once is not None)):
            raise ValueError("Only one of the input arguments should be specified")

        if (event_filter is not None) and not callable(event_filter):
            raise TypeError("Argument event_filter should be a callable")

        if (every is not None) and not (isinstance(every, numbers.Integral) and every > 0):
            raise ValueError("Argument every should be integer and greater than zero")

        if (once is not None) and not (isinstance(once, numbers.Integral) and once > 0):
            raise ValueError("Argument every should be integer and positive")

        if every is not None:
            if every == 1:
                # Just return the event itself
                event_filter = None
            else:
                event_filter = self.every_event_filter(every)

        if once is not None:
            event_filter = self.once_event_filter(once)

        # check signature:
        if event_filter is not None:
            _check_signature(event_filter, "event_filter", "engine", "event")

        return CallableEventWithFilter(self.value, event_filter, self.name)

    @staticmethod
    def every_event_filter(every: int) -> Callable:
        def wrapper(engine, event: int) -> bool:
            if event % every == 0:
                return True
            return False

        return wrapper

    @staticmethod
    def once_event_filter(once: int) -> Callable:
        def wrapper(engine, event: int) -> bool:
            if event == once:
                return True
            return False

        return wrapper

    @staticmethod
    def default_event_filter(engine, event: int) -> bool:
        return True

    def __str__(self) -> str:
        return "<event=%s, filter=%r>" % (self.name, self.filter)

    def __eq__(self, other):
        if isinstance(other, CallableEventWithFilter):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other
        else:
            raise NotImplementedError

    def __hash__(self):
        return hash(self._name_)

    def __or__(self, other):
        return EventsList() | self | other


class EventEnum(CallableEventWithFilter, Enum):
    pass


class Events(EventEnum):
    """Events that are fired by the :class:`~ignite.engine.Engine` during execution.

    Since v0.3.0, Events become more flexible and allow to pass an event filter to the Engine:

    .. code-block:: python

        engine = Engine()

        # a) custom event filter
        def custom_event_filter(engine, event):
            if event in [1, 2, 5, 10, 50, 100]:
                return True
            return False

        @engine.on(Events.ITERATION_STARTED(event_filter=custom_event_filter))
        def call_on_special_event(engine):
            # do something on 1, 2, 5, 10, 50, 100 iterations

        # b) "every" event filter
        @engine.on(Events.ITERATION_STARTED(every=10))
        def call_every(engine):
            # do something every 10th iteration

        # c) "once" event filter
        @engine.on(Events.ITERATION_STARTED(once=50))
        def call_once(engine):
            # do something on 50th iteration

    Event filter function `event_filter` accepts as input `engine` and `event` and should return True/False.
    Argument `event` is the value of iteration or epoch, depending on which type of Events the function is passed.

    """

    EPOCH_STARTED = "epoch_started"
    EPOCH_COMPLETED = "epoch_completed"

    STARTED = "started"
    COMPLETED = "completed"

    ITERATION_STARTED = "iteration_started"
    ITERATION_COMPLETED = "iteration_completed"
    EXCEPTION_RAISED = "exception_raised"

    GET_BATCH_STARTED = "get_batch_started"
    GET_BATCH_COMPLETED = "get_batch_completed"

    def __or__(self, other):
        return EventsList() | self | other


class EventsList:
    """Collection of events stacked by operator `__or__`.

    .. code-block:: python

        events = Events.STARTED | Events.COMPLETED
        events |= Events.ITERATION_STARTED(every=3)

        engine = ...

        @engine.on(events)
        def call_on_events(engine):
            # do something

    or

     .. code-block:: python

        @engine.on(Events.STARTED | Events.COMPLETED | Events.ITERATION_STARTED(every=3))
        def call_on_events(engine):
            # do something

    """

    def __init__(self):
        self._events = []

    def _append(self, event: Union[Events, CallableEventWithFilter]):
        if not isinstance(event, (Events, CallableEventWithFilter)):
            raise ValueError("Argument event should be Events or CallableEventWithFilter, got: {}".format(type(event)))
        self._events.append(event)

    def __getitem__(self, item):
        return self._events[item]

    def __iter__(self):
        return iter(self._events)

    def __len__(self):
        return len(self._events)

    def __or__(self, other: Union[Events, CallableEventWithFilter]):
        self._append(event=other)
        return self


class State:
    """An object that is used to pass internal and user-defined state between event handlers. By default, state
    contains the following attributes:

    .. code-block:: python

        state.iteration         # 1-based, the first iteration is 1
        state.epoch             # 1-based, the first epoch is 1
        state.seed              # seed to set at each epoch
        state.dataloader        # data passed to engine
        state.epoch_length      # optional length of an epoch
        state.max_epochs        # number of epochs to run
        state.batch             # batch passed to `process_function`
        state.output            # output of `process_function` after a single iteration
        state.metrics           # dictionary with defined metrics if any
        state.times             # dictionary with total and per-epoch times fetched on
                                # keys: Events.EPOCH_COMPLETED.name and Events.COMPLETED.name

    """

    event_to_attr = {
        Events.GET_BATCH_STARTED: "iteration",
        Events.GET_BATCH_COMPLETED: "iteration",
        Events.ITERATION_STARTED: "iteration",
        Events.ITERATION_COMPLETED: "iteration",
        Events.EPOCH_STARTED: "epoch",
        Events.EPOCH_COMPLETED: "epoch",
        Events.STARTED: "epoch",
        Events.COMPLETED: "epoch",
    }

    def __init__(self, **kwargs):
        self.iteration = 0
        self.epoch = 0
        self.epoch_length = None
        self.max_epochs = None
        self.output = None
        self.batch = None
        self.metrics = {}
        self.dataloader = None
        self.seed = None
        self.times = {Events.EPOCH_COMPLETED.name: None, Events.COMPLETED.name: None}

        for k, v in kwargs.items():
            setattr(self, k, v)

        for value in self.event_to_attr.values():
            if not hasattr(self, value):
                setattr(self, value, 0)

    def get_event_attrib_value(self, event_name: Union[CallableEventWithFilter, Enum]) -> int:
        if event_name not in State.event_to_attr:
            raise RuntimeError("Unknown event name '{}'".format(event_name))
        return getattr(self, State.event_to_attr[event_name])

    def __repr__(self) -> str:
        s = "State:\n"
        for attr, value in self.__dict__.items():
            if not isinstance(value, (numbers.Number, str)):
                value = type(value)
            s += "\t{}: {}\n".format(attr, value)
        return s


class RemovableEventHandle:
    """A weakref handle to remove a registered event.

    A handle that may be used to remove a registered event handler via the
    remove method, with-statement, or context manager protocol. Returned from
    :meth:`~ignite.engine.Engine.add_event_handler`.


    Args:
        event_name: Registered event name.
        handler: Registered event handler, stored as weakref.
        engine: Target engine, stored as weakref.

    Example usage:

    .. code-block:: python

        engine = Engine()

        def print_epoch(engine):
            print("Epoch: {}".format(engine.state.epoch))

        with engine.add_event_handler(Events.EPOCH_COMPLETED, print_epoch):
            # print_epoch handler registered for a single run
            engine.run(data)

        # print_epoch handler is now unregistered
    """

    def __init__(self, event_name: Union[CallableEventWithFilter, Enum, EventsList], handler: Callable, engine):
        self.event_name = event_name
        self.handler = weakref.ref(handler)
        self.engine = weakref.ref(engine)

    def remove(self) -> None:
        """Remove handler from engine."""
        handler = self.handler()
        engine = self.engine()

        if handler is None or engine is None:
            return

        if isinstance(self.event_name, EventsList):
            for e in self.event_name:
                if engine.has_event_handler(handler, e):
                    engine.remove_event_handler(handler, e)
        else:
            if engine.has_event_handler(handler, self.event_name):
                engine.remove_event_handler(handler, self.event_name)

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs) -> None:
        self.remove()
