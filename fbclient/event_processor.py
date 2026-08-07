import json
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Full, Queue
from threading import BoundedSemaphore, Condition, Event, Lock, Thread, current_thread
from typing import List, Optional

from fbclient.common_types import FBEvent
from fbclient.config import Config
from fbclient.event_types import (EventMessage, FlagEvent, MessageType,
                                  MetricEvent, UserEvent)
from fbclient.interfaces import EventProcessor, Sender
from fbclient.utils import log
from fbclient.utils.repeatable_task import RepeatableTask


_THREAD_JOIN_TIMEOUT_SECONDS = 5.0


class DefaultEventProcessor(EventProcessor):
    def __init__(self, config: Config, sender: Sender):
        self.__inbox = Queue(maxsize=config.events_max_in_queue)
        self.__closed = False
        self.__lock = Lock()
        self.__dispatcher = EventDispatcher(config, sender, self.__inbox)
        self.__dispatcher.start()
        self.__flush_task = RepeatableTask('featbit-insight-flush', config.events_flush_interval, self.flush)
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
        except Full:
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
        with self.__lock:
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
        with self.__lock:
            if not self.__closed:
                self.__put_message_async(MessageType.FLUSH)

    def stop(self):
        with self.__lock:
            if self.__closed:
                return
            # Close the producer gate atomically so no application thread can
            # append an event behind the shutdown marker.
            self.__closed = True
        log.info('FB Python SDK: event processor is stopping')
        self.__flush_task.stop()
        if current_thread() is self.__dispatcher:
            # A synchronous shutdown message cannot be consumed while this
            # thread is still executing stop(). Ask the dispatcher loop to
            # drain everything accepted before the producer gate closed and
            # then perform its normal shutdown sequence.
            self.__dispatcher.request_shutdown()
            return
        # Shutdown itself performs a final synchronous flush. Unlike a normal
        # FLUSH message, the shutdown marker is guaranteed to enter a full
        # inbox, so accepted events cannot be stranded during close.
        self.__put_message_and_wait_terminate(MessageType.SHUTDOWN)
        self.__dispatcher.join(_THREAD_JOIN_TIMEOUT_SECONDS)
        if self.__dispatcher.is_alive():
            log.warning('FB Python SDK: event dispatcher did not stop in time')


class EventDispatcher(Thread):

    __MAX_FLUSH_WORKERS_NUMBER = 5
    __BATCH_SIZE = 50

    def __init__(self, config: Config, sender: Sender, inbox: "Queue[EventMessage]"):
        super().__init__(name='featbit-event-dispatcher', daemon=True)
        self.__config = config
        self.__inbox = inbox
        self.__closed = False
        self.__shutdown_requested = Event()
        self.__sender = sender
        self.__events_buffer_to_next_flush = []
        self.__flush_workers = ThreadPoolExecutor(max_workers=self.__MAX_FLUSH_WORKERS_NUMBER)
        self.__permits = BoundedSemaphore(value=self.__MAX_FLUSH_WORKERS_NUMBER)
        self.__lock = Condition(Lock())

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
                    shutdown = False
                    try:
                        if msg.type == MessageType.FLAGS or msg.type == MessageType.METRICS or msg.type == MessageType.USER:
                            self.__put_events_to_buffer(msg.event)  # type: ignore
                        elif msg.type == MessageType.FLUSH:
                            self.__trigger_flush()
                        elif msg.type == MessageType.SHUTDOWN:
                            self.__shutdown()
                            shutdown = True
                    except Exception as inner:
                        log.exception('FB Python SDK: unexpected error in event dispatcher: %s' % str(inner))
                    finally:
                        # Synchronous callers must never wait forever because a
                        # dispatcher operation failed.
                        msg.completed()
                    if shutdown:
                        return  # exit the loop
                # stop() can be called by code already running on this thread.
                # Once producers are closed, an empty inbox means every event
                # accepted before shutdown has now reached the buffer.
                if self.__shutdown_requested.is_set() and self.__inbox.empty():
                    self.__shutdown()
                    return
            except Exception as outer:
                log.exception('FB Python SDK: unexpected error in event dispatcher: %s' % str(outer))

    def request_shutdown(self):
        self.__shutdown_requested.set()

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
        def flush_payload_done(fn):
            self.__permits.release()
            with self.__lock:
                self.__lock.notify_all()

        if not self.__closed and len(self.__events_buffer_to_next_flush) > 0:
            log.debug('trigger flush')
            # get all the current events from event buffer
            if self.__permits.acquire(blocking=False):
                payloads = []
                payloads.extend(self.__events_buffer_to_next_flush)
                # get an available flush worker to send events
                self.__flush_workers \
                    .submit(FlushPayloadRunner(self.__config, self.__sender, payloads).run) \
                    .add_done_callback(flush_payload_done)
                # clear the buffer for the next flush
                self.__events_buffer_to_next_flush.clear()
            # if no available flush worker, keep the events in the buffer

    def __shutdown(self):
        if not self.__closed:
            try:
                with self.__lock:
                    log.debug('event dispatcher is cleaning up thread and conn pool')
                    self.__wait_until_flush_playload_worker_down()
                if self.__events_buffer_to_next_flush:
                    payloads = list(self.__events_buffer_to_next_flush)
                    self.__events_buffer_to_next_flush.clear()
                    # All asynchronous workers are down, so a direct final
                    # send is safe and guarantees delivery of the buffer that
                    # existed when shutdown was accepted.
                    FlushPayloadRunner(self.__config, self.__sender, payloads).run()
                self.__closed = True
            except Exception as e:
                log.exception('FB Python SDK: unexpected error when closing event dispatcher: %s' % str(e))
            finally:
                try:
                    self.__closed = True
                    log.debug('flush worker pool is stopping...')
                    self.__flush_workers.shutdown(wait=True)
                except Exception:
                    log.exception('FB Python SDK: could not stop event flush workers')
                try:
                    self.__sender.stop()
                except Exception:
                    log.exception('FB Python SDK: could not stop event sender')

    def __wait_until_flush_playload_worker_down(self):
        while self.__permits._value != self.__MAX_FLUSH_WORKERS_NUMBER:
            self.__lock.wait()


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
