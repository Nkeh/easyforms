import concurrent.futures

# socket_connect_timeout/socket_timeout on a Redis client only bound the TCP
# connect()/read() phase — they do NOT bound socket.getaddrinfo() (DNS
# resolution), which precedes connect() and can block far longer (measured:
# ~4s against a hostname that stopped resolving) regardless of any
# client-side timeout setting. Running the call in a worker thread and only
# waiting up to `timeout` for it lets the caller give up on schedule even
# when the call itself is still blocked in the unbounded DNS phase.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="redis-bound")


def run_bounded(func, timeout: float):
    """Run func() (a zero-arg callable — bind any arguments with a lambda
    or functools.partial at the call site) in a worker thread, waiting at
    most `timeout` seconds. Raises TimeoutError if it doesn't finish in
    time. Python cannot forcibly cancel a blocked thread, so the abandoned
    call keeps running in the background until it naturally completes (here,
    until the OS/resolver's own DNS timeout elapses) and its result is then
    just discarded — this bounds the *caller's* wait, not the underlying
    blocking call itself.
    """
    future = _executor.submit(func)
    return future.result(timeout=timeout)
