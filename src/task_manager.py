import gevent
import gevent.event
import time
from typing import Callable
import logging

from app_core import app

logger = logging.getLogger(__name__)

#
# Task classes
#

class Task:
    _name: str
    _func: Callable
    _interval_minutes: int
    _params: list
    _last: float

    def __init__(self, name: str, func: Callable, interval_minutes: int, params: list):
        self._name = name
        self._func = func  # type: ignore
        self._interval_minutes = interval_minutes
        self._params = params
        self._last = time.time()

    def run_if_time(self, now: float):
        if self._last + (self._interval_minutes * 60) <= now:
            self._last = now
            self.run()

    def run(self):
        # ensure we have an app context and call task function
        with app.app_context():
            try:
                self._func(*(self._params))
            except Exception as e:
                logger.error('exception in task (%s): %s', self._name, e)


class TaskNonTerminating:
    _name: str
    _func: Callable
    _greenlet: gevent.Greenlet

    def __init__(self, name: str, func: Callable):
        self._name = name
        self._func = func  # type: ignore
        self._greenlet = gevent.Greenlet(func)

    def start(self):
        self._greenlet.start()

    def kill(self):
        self._greenlet.kill()

    def greenlet(self):
        return self._greenlet

class TaskManager:
    _repeated_tasks: list[Task] = []
    _one_off_tasks: list[Task] = []
    _non_terminating_tasks: list[TaskNonTerminating] = []

    def __init__(self):
        self._task_loop_event = gevent.event.Event()
        self._task_loop_greenlet = gevent.Greenlet(self._task_loop)

    def _task_loop(self):
        while True:
            self._task_loop_event.wait(timeout=5)
            self._task_loop_event.clear()
            # one off tasks
            while len(self._one_off_tasks):
                task = self._one_off_tasks.pop(0)
                task.run()
            # repeated tasks
            now = time.time()
            for task in self._repeated_tasks:
                task.run_if_time(now)

    def start(self):
        self._task_loop_greenlet.start()
        for task in self._non_terminating_tasks:
            task.start()

    def kill(self):
        for task in self._non_terminating_tasks:
            task.kill()
        self._task_loop_greenlet.kill()
        greenlets = [t.greenlet() for t in self._non_terminating_tasks]
        greenlets.append(self._task_loop_greenlet)
        return greenlets

    def repeated(self, name: str, func: Callable, interval_minutes: int):
        self._repeated_tasks.append(Task(name, func, interval_minutes, []))

    def one_off(self, name: str, func: Callable, params: list = []):
        self._one_off_tasks.append(Task(name, func, 0, params))
        self._task_loop_event.set()

    def non_terminating(self, name: str, func: Callable):
        # must be called before `start()`
        self._non_terminating_tasks.append(TaskNonTerminating(name, func))
