"""Measure how the real-time engine keeps up under load.

The script starts its own redis, a web process and a worker for a scratch
experiment, with the runner the worker starts beside it. It then plays
sessions with simulated players and writes what it measured as JSON::

    .venv/bin/python benchmarks/realtime.py --output realtime.json

Each run plays ``--sessions`` sessions of ``--players`` players, each sending
``--rate`` messages a second, in a game that ticks ``--tick-rate`` times a
second. There are four runs: one with ``send_views_on_messages`` on and one
with it off, each with and without CPU-bound jobs on the worker beside the
runner's own records jobs. ``--views`` and ``--cpu-load`` pick fewer.

Each run is measured for ``--duration`` seconds, after ``--warmup`` seconds.
Timings are percentiles in milliseconds:

- ``ack_latency_ms``: from a player sending a message to the player getting
  the first view that reports the message processed, with the worst in each
  second in ``ack_latency_max_ms_by_second``
- ``view_spacing_ms``: between the tick views a player gets
- ``tick_lateness_ms``: how far past a tick's time the runner played it, on
  the session's clock, taking the earliest tick of a pass that played several.
  One player in each session measures it.
- ``view_delay_ms``: from the runner starting the step that played a view's
  session to the player getting the view, which covers playing, saving and
  sending every session in the step as well as delivery
- ``player_send_lag_ms``: how late players sent their messages, and
  ``player_stall_ms``: how much longer than 5 milliseconds a sleeping thread
  in a player process took to wake, with the worst in each second in
  ``player_stall_max_ms_by_second``. Large values mean the players, or the
  machine, held up the measurements rather than the engine.
- ``cpu_cores``: the CPU used by the web processes, the workers (which run
  the CPU-bound jobs and the records jobs), the runners, redis, the player
  processes and this script, in cores, with the busiest player process in
  ``player_process_cores_max``, and the machine's 1, 5 and 15 minute
  ``load_average`` as measuring ended
- ``messages_per_second`` sent while measuring, ``views_per_second`` received
  over the whole run, ``unacked_messages`` sent while measuring that no view
  acknowledged, and ``rejected_messages`` over the whole run
- ``runner_slow_warnings`` and ``web_dropped_warnings``: how many times the
  runners warned that they fell behind and the web processes that they
  dropped messages, while measuring. Each warning is logged at most every few
  seconds, so these say whether it happened rather than how often.
- ``records_drain_seconds``: from the sessions being ended to every ending
  being saved in Postgres, and ``session_statuses``: how many of the sessions
  ended and how many failed
- ``errors``: the first players' errors, if any

It needs Postgres, with a role that can create the ``dallinger_benchmark``
database, which it empties, and ``redis-server`` 7.0 or later on ``PATH``.
The scratch experiment's directory, with each process's log, is kept and its
path printed. The JSON is rewritten after each run, so the runs finished so
far are kept if one fails.
"""

import argparse
import json
import math
import multiprocessing
import os
import platform
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse

BIN = os.path.dirname(sys.executable)

SETTINGS = (
    "sessions",
    "players",
    "rate",
    "tick_rate",
    "duration",
    "warmup",
    "cpu_jobs_per_second",
    "cpu_job_seconds",
    "web_processes",
    "workers",
    "client_processes",
)

VIEWS_ON = "bench_views"
VIEWS_OFF = "bench_quiet"

# Seconds players keep listening after they stop sending, so the last
# messages measured are acknowledged.
GRACE = 1.0

# Seconds between creating a run's sessions and its players sending, so every
# player has connected.
CONNECT_TIME = 3.0

EXPERIMENT = """
import time

from dallinger.experiment import Experiment
from dallinger.realtime import RealtimeGame, Reject


def burn(seconds):
    end = time.process_time() + seconds
    while time.process_time() < end:
        pass


class Bench(RealtimeGame):
    channel = "VIEWS_ON"
    tick_rate = TICK_RATE
    join_timeout = None
    max_messages_per_second = MAX_RATE

    def initial_state(self, players):
        return {"positions": {player: [0, 0] for player in players}, "ticks": 0}

    def apply(self, state, player_id, message, now, sent):
        move = message.get("move") if isinstance(message, dict) else None
        if not (isinstance(move, list) and len(move) == 2):
            raise Reject("a move is [dx, dy]")
        position = state["positions"][player_id]
        position[0] += move[0]
        position[1] += move[1]

    def tick(self, state, now):
        state["ticks"] += 1

    def view(self, state, player_id):
        return state


class BenchQuiet(Bench):
    channel = "VIEWS_OFF"
    send_views_on_messages = False


class Benchmark(Experiment):
    realtime_games = [Bench, BenchQuiet]
"""

CONFIG = """
[Experiment]
mode = debug

[Server]
threads = WEB_PROCESSES
loglevel = 2
loglevel_worker = 2
logfile = -
host = 127.0.0.1
"""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add = parser.add_argument
    add("--sessions", type=int, default=20, help="sessions per run")
    add("--players", type=int, default=4, help="players per session")
    add("--rate", type=float, default=50, help="messages a second per player")
    add("--tick-rate", type=float, default=20, help="ticks a second")
    add("--duration", type=float, default=30, help="seconds measured per run")
    add("--warmup", type=float, default=5, help="seconds before measuring")
    add("--views", choices=["on", "off", "both"], default="both")
    add("--cpu-load", choices=["on", "off", "both"], default="both")
    add("--cpu-jobs-per-second", type=float, default=10)
    add("--cpu-job-seconds", type=float, default=0.05)
    add("--web-processes", type=int, default=1)
    add("--workers", type=int, default=1, help="worker processes, each with a runner")
    add("--client-processes", type=int, default=4)
    add(
        "--database-url",
        default="postgresql://dallinger:dallinger@localhost/dallinger_benchmark",
        help="emptied before the runs",
    )
    add("--port", type=int, default=0, help="the web process's port; 0 picks one")
    add("--output", help="where to write the JSON; standard output if not given")
    args = parser.parse_args(argv)
    if args.tick_rate <= 0:
        parser.error("--tick-rate must be positive")
    if args.rate <= 0:
        parser.error("--rate must be positive")
    return args


def choices(value):
    return {"on": [True], "off": [False], "both": [True, False]}[value]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(check, timeout, what):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise RuntimeError("Timed out waiting for {}.".format(what))
        time.sleep(0.1)


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def ensure_database(url):
    import psycopg2

    parsed = urlparse(url)
    name = parsed.path.lstrip("/")
    connection = psycopg2.connect(parsed._replace(path="/postgres").geturl())
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone() is None:
                cursor.execute('CREATE DATABASE "{}"'.format(name))
    finally:
        connection.close()


class Processes:
    """The redis, web and worker processes, each logging to a file in the
    experiment's directory.
    """

    def __init__(self, directory, env):
        self.directory = directory
        self.env = env
        self.started = {}

    def start(self, name, command):
        log = open(os.path.join(self.directory, name + ".log"), "w")
        self.started[name] = subprocess.Popen(
            command,
            cwd=self.directory,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log.close()
        return self.started[name]

    def log_size(self, name):
        return os.path.getsize(os.path.join(self.directory, name + ".log"))

    def count_in_log(self, name, text, since, until):
        """Count the lines containing ``text`` between two of a log's sizes."""
        with open(os.path.join(self.directory, name + ".log"), "rb") as log:
            log.seek(since)
            lines = log.read(until - since).decode(errors="replace").splitlines()
        return sum(text in line for line in lines)

    def stop(self):
        # Workers first, so their runners give up their sessions while redis
        # is still there, and redis last.
        for name in sorted(self.started, key=lambda each: each == "redis"):
            process = self.started[name]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, 9)
                    process.wait()


class CpuMeter:
    """CPU time used by the web processes, the workers, the runners, redis
    and the player processes, all children of this process.
    """

    def __init__(self, processes):
        self.processes = processes

    def groups(self):
        import psutil

        started = self.processes.started
        server = {process.pid for process in started.values()}
        groups = {"web": [], "worker": [], "runner": [], "redis": []}
        for name, process in started.items():
            try:
                parent = psutil.Process(process.pid)
                children = parent.children(recursive=True)
            except psutil.NoSuchProcess:
                continue
            if name == "web":
                groups["web"] += [parent, *children]
            elif name.startswith("worker"):
                groups["worker"].append(parent)
                groups["runner"] += children
            else:
                groups["redis"].append(parent)
        groups["players"] = [
            child for child in psutil.Process().children() if child.pid not in server
        ]
        groups["script"] = [psutil.Process()]
        return groups

    def snapshot(self):
        import psutil

        totals = {}
        for group, members in self.groups().items():
            total = 0.0
            for member in members:
                try:
                    times = member.cpu_times()
                except psutil.NoSuchProcess:
                    continue
                total += times.user + times.system
            totals[group] = total
        return time.monotonic(), totals


def cores_used(before, after):
    elapsed = after[0] - before[0]
    return {
        group: round((after[1][group] - before[1].get(group, 0)) / elapsed, 3)
        for group in after[1]
    }


def summary(values, scale=1000):
    """Percentiles of ``values``, scaled to milliseconds by default."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def at(fraction):
        return round(
            ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] * scale, 3
        )

    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered) * scale, 3),
        "p50": at(0.5),
        "p90": at(0.9),
        "p99": at(0.99),
        "max": round(ordered[-1] * scale, 3),
    }


def play_player(port, channel, rate, tick_rate, player, times, out):
    """Play one player: send ``rate`` messages a second from ``times``'s
    start until its stop, and note what it measures in ``out``.

    :param player: a ``(session_id, participant_id, measures_ticks)`` triple, where
        ``measures_ticks`` says whether this player measures its session's tick
        lateness
    """
    session_id, player, measures_ticks = player
    import simple_websocket

    start_at, measure_at, stop_at = times
    measuring = lambda moment: measure_at <= moment < stop_at  # noqa: E731
    url = "ws://127.0.0.1:{}/chat?participant_id={}&session={}".format(
        port, player, session_id
    )
    try:
        ws = simple_websocket.Client.connect(url)
    except Exception as error:
        out["errors"].append("connect: {!r}".format(error))
        return
    # Browsers set TCP_NODELAY. Without it, Nagle's algorithm holds a small
    # frame until the server acknowledges the last one, which Linux delays by
    # up to 40 milliseconds when the server has nothing to send back.
    ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sent_at = []
    acked = -1
    view_time = None
    last_tick_received = None
    last_tick_time = None
    interval = 1 / rate
    next_send = start_at + random.random() * interval
    try:
        while True:
            now = time.time()
            if now >= stop_at + GRACE:
                break
            if start_at <= now < stop_at and now >= next_send:
                envelope = {
                    "number": len(sent_at),
                    "browser_time": now,
                    "view_time": view_time,
                }
                sent_at.append(now)
                if measuring(now):
                    out["send_lag"].append(now - next_send)
                ws.send(
                    channel
                    + ":"
                    + json.dumps({"envelope": envelope, "payload": {"move": [1, 0]}})
                )
                next_send += interval
                if next_send < now - interval:
                    next_send = now
                continue
            wake = next_send if now < stop_at else stop_at + GRACE
            frame = ws.receive(timeout=max(min(wake, stop_at + GRACE) - now, 0))
            if frame is None:
                continue
            received = time.time()
            payload = json.loads(frame.partition(":")[2])
            if payload.get("type") != "realtime_view":
                continue
            view = payload["view"]
            view_time = view["time"]
            out["views"] += 1
            processed = view["last_processed"]
            if processed is not None and processed > acked:
                for number in range(acked + 1, processed + 1):
                    if measuring(sent_at[number]):
                        out["ack"].append(received - sent_at[number])
                        out["ack_at"].append(sent_at[number])
                acked = processed
            out["rejected"] += len(view["rejected"])
            if not measuring(received):
                if view["kind"] == "tick":
                    last_tick_received, last_tick_time = received, view["time"]
                continue
            out["delay"].append(received - view["clock"])
            if view["kind"] != "tick":
                continue
            if last_tick_received is not None:
                out["spacing"].append(received - last_tick_received)
            if last_tick_received is not None and measures_ticks:
                # Ticks fall at whole multiples of the tick interval, and the
                # first one this pass played follows the last one before it.
                first_tick = (
                    math.floor(last_tick_time * tick_rate + 1e-6) + 1
                ) / tick_rate
                out["lateness"].append(view["time"] - first_tick)
            last_tick_received, last_tick_time = received, view["time"]
    except Exception as error:
        out["errors"].append("{}: {!r}".format(player, error))
    finally:
        ws.close()
    measured = [number for number, at in enumerate(sent_at) if measuring(at)]
    out["sent"] += len(measured)
    out["unacked"] += sum(number > acked for number in measured)


def play_players(port, channel, rate, tick_rate, players, times):
    """Play ``players``, each in its own thread, and return what they
    measured.
    """
    outs = [new_tally() for _ in players]
    probe = new_tally()
    prober = threading.Thread(target=probe_stalls, args=(times, probe))
    prober.start()
    threads = [
        threading.Thread(
            target=play_player,
            args=(port, channel, rate, tick_rate, player, times, out),
        )
        for player, out in zip(players, outs)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    prober.join()
    return merge_tallies(outs + [probe])


#: Seconds the stall probe sleeps for each time.
PROBE_SLEEP = 0.005


def probe_stalls(times, out):
    """Note, in ``out``, how much longer than :data:`PROBE_SLEEP` each of a
    thread's sleeps took while measuring, which is how long the players'
    process kept a ready thread waiting, and the process's CPU use.
    """
    _, measure_at, stop_at = times
    sleep_until(measure_at)
    cpu_before = time.process_time()
    while time.time() < stop_at:
        began = time.perf_counter()
        time.sleep(PROBE_SLEEP)
        out["stall"].append(time.perf_counter() - began - PROBE_SLEEP)
        out["stall_at"].append(time.time())
    out["process_cores"].append(
        (time.process_time() - cpu_before) / (stop_at - measure_at)
    )


def new_tally():
    return {
        "ack": [],
        "spacing": [],
        "lateness": [],
        "delay": [],
        "ack_at": [],
        "send_lag": [],
        "stall": [],
        "stall_at": [],
        "process_cores": [],
        "errors": [],
        "sent": 0,
        "unacked": 0,
        "views": 0,
        "rejected": 0,
    }


def merge_tallies(tallies):
    merged = new_tally()
    for tally in tallies:
        for key, value in tally.items():
            merged[key] += value
    return merged


class Bench:
    def __init__(self, args, directory, processes, pool, port):
        self.args = args
        self.directory = directory
        self.processes = processes
        self.pool = pool
        self.port = port
        self.cpu = CpuMeter(processes)
        self.next_player = 1

    def run(self, views_on, cpu_load):
        from dallinger.db import get_queue
        from dallinger.realtime import create_realtime_session, end_realtime_session
        from dallinger.realtime.store import experiment_games

        args = self.args
        channel = VIEWS_ON if views_on else VIEWS_OFF
        game_type = type(experiment_games()[channel])
        players = []
        session_ids = []
        for _ in range(args.sessions):
            members = [str(self.next_player + each) for each in range(args.players)]
            self.next_player += args.players
            session_id = create_realtime_session(game_type, members)
            session_ids.append(session_id)
            players += [
                (session_id, member, member == members[0]) for member in members
            ]

        start_at = time.time() + CONNECT_TIME
        measure_at = start_at + args.warmup
        stop_at = measure_at + args.duration
        groups = [
            players[each :: args.client_processes]
            for each in range(args.client_processes)
        ]
        pending = self.pool.starmap_async(
            play_players,
            [
                (
                    self.port,
                    channel,
                    args.rate,
                    args.tick_rate,
                    group,
                    (start_at, measure_at, stop_at),
                )
                for group in groups
                if group
            ],
        )

        stopping = threading.Event()
        if cpu_load:
            threading.Thread(
                target=feed_cpu_jobs,
                args=(get_queue("default"), args, start_at, stopping),
                daemon=True,
            ).start()
        workers = ["worker-{}".format(each) for each in range(args.workers)]
        logs = workers + ["web"]
        try:
            sleep_until(measure_at)
            log_starts = {name: self.processes.log_size(name) for name in logs}
            before = self.cpu.snapshot()
            sleep_until(stop_at)
            after = self.cpu.snapshot()
            log_ends = {name: self.processes.log_size(name) for name in logs}
            load_average = [round(each, 2) for each in os.getloadavg()]
        finally:
            stopping.set()
        results = pending.get()

        ended_at = time.monotonic()
        for session_id in session_ids:
            end_realtime_session(session_id, "benchmark_over")
        statuses = wait_for_endings(session_ids)
        drain = time.monotonic() - ended_at
        wait_for(lambda: not jobs_left(), 120, "the jobs to finish")

        def warnings(name, text):
            return self.processes.count_in_log(
                name, text, log_starts[name], log_ends[name]
            )

        merged = merge_tallies(results)
        return {
            "views_on_messages": views_on,
            "cpu_load": cpu_load,
            "ack_latency_ms": summary(merged["ack"]),
            "ack_latency_max_ms_by_second": worst_by_second(
                merged["ack_at"], merged["ack"], measure_at, args.duration
            ),
            "view_spacing_ms": summary(merged["spacing"]),
            "tick_lateness_ms": summary(merged["lateness"]),
            "view_delay_ms": summary(merged["delay"]),
            "messages_per_second": round(merged["sent"] / args.duration, 1),
            "views_per_second": round(
                merged["views"] / (stop_at + GRACE - start_at), 1
            ),
            "unacked_messages": merged["unacked"],
            "rejected_messages": merged["rejected"],
            "player_send_lag_ms": summary(merged["send_lag"]),
            "player_stall_ms": summary(merged["stall"]),
            "player_stall_max_ms_by_second": worst_by_second(
                merged["stall_at"], merged["stall"], measure_at, args.duration
            ),
            "load_average": load_average,
            "player_process_cores_max": round(max(merged["process_cores"]), 3),
            "cpu_cores": cores_used(before, after),
            "records_drain_seconds": round(drain, 2),
            "session_statuses": statuses,
            "runner_slow_warnings": sum(
                warnings(name, "to play, save and send") for name in workers
            ),
            "web_dropped_warnings": warnings("web", "Dropping messages"),
            "errors": merged["errors"][:20],
        }


def worst_by_second(times, values, start, duration):
    """The largest of ``values`` in each second from ``start``, in
    milliseconds, by the matching ``times``.
    """
    worst = [0.0] * math.ceil(duration)
    for moment, value in zip(times, values):
        second = int(moment - start)
        if 0 <= second < len(worst):
            worst[second] = max(worst[second], value)
    return [round(value * 1000, 1) for value in worst]


def sleep_until(moment):
    time.sleep(max(moment - time.time(), 0))


def feed_cpu_jobs(queue, args, start_at, stopping):
    interval = 1 / args.cpu_jobs_per_second
    next_job = start_at
    while not stopping.wait(max(next_job - time.time(), 0)):
        queue.enqueue("dallinger_experiment.experiment.burn", args.cpu_job_seconds)
        next_job += interval


def jobs_left():
    """How many jobs are queued or running on the queues the runner uses."""
    from rq.registry import StartedJobRegistry

    from dallinger.db import get_queue

    queues = [get_queue(name) for name in ("high", "default")]
    return sum(queue.count + StartedJobRegistry(queue=queue).count for queue in queues)


def wait_for_endings(session_ids):
    from dallinger import db
    from dallinger.models import RealtimeSession

    def statuses():
        rows = (
            db.session.query(RealtimeSession.status)
            .filter(RealtimeSession.id.in_(session_ids))
            .all()
        )
        db.session.rollback()
        counted = {}
        for (status,) in rows:
            counted[status] = counted.get(status, 0) + 1
        return counted

    wait_for(lambda: "running" not in statuses(), 300, "the sessions' endings")
    return statuses()


def environment():
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    ).stdout.strip()
    return {
        "commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_model": cpu_model(),
        "cpu_count": os.cpu_count(),
    }


def cpu_model():
    if sys.platform == "darwin":
        return subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True
        ).stdout.strip()
    try:
        with open("/proc/cpuinfo") as cpuinfo:
            for line in cpuinfo:
                if line.startswith("model name"):
                    return line.partition(":")[2].strip()
    except OSError:
        pass
    return platform.processor()


def main(argv=None):
    args = parse_args(argv)
    output = os.path.abspath(args.output) if args.output else None
    directory = tempfile.mkdtemp(prefix="realtime-benchmark-")
    port = args.port or free_port()
    redis_port = free_port()
    env = {
        **os.environ,
        "PATH": BIN + os.pathsep + os.environ.get("PATH", ""),
        "DATABASE_URL": args.database_url,
        "REDIS_URL": "redis://127.0.0.1:{}".format(redis_port),
        "FLASK_SECRET_KEY": os.urandom(16).hex(),
        "PORT": str(port),
    }
    os.environ.update(env)
    experiment = (
        EXPERIMENT.replace("VIEWS_ON", VIEWS_ON)
        .replace("VIEWS_OFF", VIEWS_OFF)
        .replace("TICK_RATE", repr(args.tick_rate))
        .replace("MAX_RATE", repr(max(120, 2 * args.rate)))
    )
    with open(os.path.join(directory, "experiment.py"), "w") as file:
        file.write(experiment)
    open(os.path.join(directory, "__init__.py"), "w").close()
    with open(os.path.join(directory, "config.txt"), "w") as file:
        file.write(CONFIG.replace("WEB_PROCESSES", str(args.web_processes)))
    print("Experiment and logs in {}".format(directory), file=sys.stderr)

    processes = Processes(directory, env)
    pool = None
    try:
        processes.start(
            "redis",
            [
                "redis-server",
                "--port",
                str(redis_port),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
        )
        wait_for(lambda: port_open(redis_port), 10, "redis")
        ensure_database(args.database_url)
        os.chdir(directory)
        from dallinger import db
        from dallinger.config import get_config, initialize_experiment_package
        from dallinger.realtime import store

        initialize_experiment_package(directory)
        get_config().load()
        db.init_db(drop_all=True)

        processes.start("web", [os.path.join(BIN, "dallinger_heroku_web")])
        for each in range(args.workers):
            processes.start(
                "worker-{}".format(each), [os.path.join(BIN, "dallinger_heroku_worker")]
            )
        wait_for(lambda: port_open(port), 60, "the web process")
        wait_for(
            lambda: db.redis_conn.zcard(store.RUNNERS) >= args.workers,
            60,
            "the runners",
        )
        pool = multiprocessing.get_context("spawn").Pool(args.client_processes)
        bench = Bench(args, directory, processes, pool, port)
        result = {
            "settings": {key: getattr(args, key) for key in SETTINGS},
            "environment": environment(),
            "runs": [],
        }
        for views_on in choices(args.views):
            for cpu_load in choices(args.cpu_load):
                print(
                    "Run: views on messages {}, CPU load {}".format(
                        "on" if views_on else "off", "on" if cpu_load else "off"
                    ),
                    file=sys.stderr,
                )
                result["runs"].append(bench.run(views_on, cpu_load))
                print(json.dumps(result["runs"][-1], indent=2), file=sys.stderr)
                if output:
                    with open(output, "w") as file:
                        file.write(json.dumps(result, indent=2) + "\n")
    finally:
        if pool is not None:
            pool.terminate()
        processes.stop()
    if not output:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
