import json
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from threading import BoundedSemaphore, Lock, Thread
from typing import List, Optional

from fbclient.common_types import FBEvent
from fbclient.config import Config
from fbclient.event_types import (EventMessage, FlagEvent, MessageType,
                                  MetricEvent, UserEvent)
from fbclient.interfaces import EventProcessor, Sender
from fbclient.utils import log
from fbclient.utils.repeatable_task import RepeatableTask


class DefaultEventProcessor(EventProcessor):
    def __init__(self, config: Config, sender: Sender):
        self.__inbox = Queue(maxsize=config.events_max_in_queue)
        self.__closed = False
        self.__lock = Lock()
        EventDispatcher(config, sender, self.__inbox).start()
        self.__flush_task = RepeatableTask('insight flush', config.events_flush_interval, self.flush)
        self.__flush_task.start()
        log.debug('insight processor is ready')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.stop()

    def __put_message_to_inbox(self, message: EventMessage) -> bool:
        try:
            self.__inbox.put_nowait(message)
            return True
        except:
            if message.type == MessageType.SHUTDOWN:
                # must put the shut down to inbox;
                self.__inbox.put(message, block=True, timeout=None)
                return True
            #  if it reaches here, it means the application is probably doing tons of flag
            #  evaluations across many threads -- so if we wait for a space in the inbox, we risk a very serious slowdown
            #  of the app. To avoid that, we'll just drop the event or you can increase the capacity of inbox
            log.warning('FB Python SDK: Events are being produced faster than they can be processed; some events will be dropped')
            return False

    def __put_message_async(self, type: MessageType, event: Optional[FBEvent] = None):
        message = EventMessage(type, event, False)
        if self.__put_message_to_inbox(message):
            log.trace('put %s message to inbox' % str(type))  # type: ignore

    def __put_message_and_wait_terminate(self, type: MessageType, event: Optional[FBEvent] = None):
        message = EventMessage(type, event, True)
        if self.__put_message_to_inbox(message):
            log.debug('put %s WaitTermination message to inbox' % str(type))
            message.waitForComplete()

    def send_event(self, event: FBEvent):
        if not self.__closed and event:
            if isinstance(event, FlagEvent):
                self.__put_message_async(MessageType.FLAGS, event)
            elif isinstance(event, MetricEvent):
                self.__put_message_async(MessageType.METRICS, event)
            elif isinstance(event, UserEvent):
                self.__put_message_async(MessageType.USER, event)
            else:
                log.debug('ignore unknown event type')

    def flush(self):
        if not self.__closed:
            self.__put_message_async(MessageType.FLUSH)

    def stop(self):
        with self.__lock:
            if not self.__closed:
                log.info('FB Python SDK: event processor is stopping')
                self.__closed = True
                self.__flush_task.stop()
                self.flush()
                self.__put_message_and_wait_terminate(MessageType.SHUTDOWN)


class EventDispatcher(Thread):

    __MAX_FLUSH_WORKERS_NUMBER = 5
    __BATCH_SIZE = 50

    def __init__(self, config: Config, sender: Sender, inbox: "Queue[EventMessage]"):
        super().__init__(daemon=True)
        self.__config = config
        self.__inbox = inbox
        self.__closed = False
        self.__sender = sender
        self.__events_buffer_to_next_flush = []
        self.__flush_workers = ThreadPoolExecutor(max_workers=self.__MAX_FLUSH_WORKERS_NUMBER)
        self.__permits = BoundedSemaphore(value=self.__MAX_FLUSH_WORKERS_NUMBER)

    # blocks until at least one message is available and then:
    # 1: transfer the events to event buffer
    # 2: try to flush events to featureflag if a flush message arrives
    # 3: wait for releasing resources if a shutdown arrives
    def run(self):
        log.debug('event dispatcher is working...')
        while True:
            try:
                msgs = self.__drain_inbox(size=self.__BATCH_SIZE)
                for msg in msgs:
                    try:
                        if msg.type == MessageType.FLAGS or msg.type == MessageType.METRICS or msg.type == MessageType.USER:
                            self.__put_events_to_buffer(msg.event)  # type: ignore
                        elif msg.type == MessageType.FLUSH:
                            self.__trigger_flush()
                        elif msg.type == MessageType.SHUTDOWN:
                            self.__shutdown()
                            msg.completed()
                            return  # exit the loop
                        msg.completed()
                    except Exception as inner:
                        log.exception('FB Python SDK: unexpected error in event dispatcher: %s' % str(inner))
            except Exception as outer:
                log.exception('FB Python SDK: unexpected error in event dispatcher: %s' % str(outer))

    def __drain_inbox(self, size=50) -> List[EventMessage]:
        msg = self.__inbox.get(block=True, timeout=None)
        msgs = [msg]
        for _ in range(size - 1):
            try:
                msg = self.__inbox.get_nowait()
                msgs.append(msg)
            except Empty:
                break
        return msgs

    def __put_events_to_buffer(self, event: FBEvent):
        if not self.__closed and event.is_send_event:
            log.debug('put event to buffer')
            self.__events_buffer_to_next_flush.append(event)

    def __trigger_flush(self):
        if not self.__closed and len(self.__events_buffer_to_next_flush) > 0:
            log.debug('trigger flush')
            # get all the current events from event buffer
            if self.__permits.acquire(blocking=False):
                payloads = []
                payloads.extend(self.__events_buffer_to_next_flush)
                # get an available flush worker to send events
                self.__flush_workers \
                    .submit(FlushPayloadRunner(self.__config, self.__sender, payloads).run) \
                    .add_done_callback(lambda x: self.__permits.release())
                # clear the buffer for the next flush
                self.__events_buffer_to_next_flush.clear()
            # if no available flush worker, keep the events in the buffer

    def __shutdown(self):
        if not self.__closed:
            try:
                log.debug('event dispatcher is cleaning up thread and conn pool')
                self.__closed = True
                log.debug('flush worker pool is stopping...')
                self.__flush_workers.shutdown(wait=True)
                self.__sender.stop()
            except Exception as e:
                log.exception('FB Python SDK: unexpected error when closing event dispatcher: %s' % str(e))


class FlushPayloadRunner:
    __MAX_EVENT_SIZE_PER_REQUEST = 50

    def __init__(self, config: Config, sender: Sender, payloads: List[FBEvent]):
        self.__config = config
        self.__sender = sender
        self.__payloads = payloads

    def run(self) -> bool:
        def partition(lst: List, size: int):
            for i in range(0, len(lst), size):
                yield lst[i : i + size]
        try:
            for payload in list(partition(self.__payloads, self.__MAX_EVENT_SIZE_PER_REQUEST)):
                payload_part = [event.to_json_dict() for event in payload]
                json_str = json.dumps(payload_part)
                log.trace(json_str)  # type: ignore
                self.__sender.postJson(self.__config.events_uri, json_str, fetch_response=False)
                log.debug('paload size: %s' % len(payload_part))
        except Exception as e:
            log.exception('FB Python SDK: unexpected error in sending payload: %s' % str(e))
            return False
        return True


class NullEventProcessor(EventProcessor):
    def __init__(self, config: Config, sender: Sender):
        pass

    def send_event(self, event: FBEvent):
        pass

    def flush(self):
        pass

    def stop(self):
        pass
