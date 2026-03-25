import queue
import signal
import threading
import time

from src.utils import log_status, log_success, log_error

# Queues for inter-layer communication
discovery_to_enrichment = queue.Queue()
enrichment_to_people = queue.Queue()
people_to_email = queue.Queue()

# Shutdown event for graceful termination
shutdown_event = threading.Event()


def start_pipeline():
    """
    Starts all four pipeline layers as daemon threads and waits for
    a keyboard interrupt (Ctrl+C) to shut down gracefully. Each layer
    runs continuously in its own thread, communicating via thread-safe
    queues.
    """
    log_status("Starting Avelero lead discovery pipeline...")

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)

    threads = [
        _create_layer_thread("Discovery", _run_discovery),
        _create_layer_thread("Enrichment", _run_enrichment),
        _create_layer_thread("People", _run_people),
        _create_layer_thread("Email Generation", _run_email_generation),
    ]

    for thread in threads:
        thread.start()

    log_success("All layers started. Press Ctrl+C to stop.")

    # Wait for shutdown signal
    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    _shutdown(threads)


def run_single_layer(layer_name):
    """
    Runs a single layer for testing purposes. The layer runs in the
    main thread until interrupted with Ctrl+C.

    Parameters:
        layer_name: One of "discovery", "enrichment", "people", "email".
    """
    signal.signal(signal.SIGINT, _signal_handler)

    layer_map = {
        "discovery": _run_discovery,
        "enrichment": _run_enrichment,
        "people": _run_people,
        "email": _run_email_generation,
    }

    layer_func = layer_map.get(layer_name)
    if not layer_func:
        log_error(f"Unknown layer: {layer_name}")
        return

    log_status(f"Running single layer: {layer_name}")
    layer_func()


def _create_layer_thread(name, target):
    """
    Creates a daemon thread for a pipeline layer.

    Parameters:
        name: Human-readable name for the thread.
        target: The function to run in the thread.

    Returns:
        A threading.Thread instance (not yet started).
    """
    thread = threading.Thread(target=target, name=name, daemon=True)
    return thread


def _run_discovery():
    """Wrapper that runs the discovery layer with error recovery."""
    from src.layers.discovery import run_discovery_layer
    _run_with_recovery("Discovery", run_discovery_layer)


def _run_enrichment():
    """Wrapper that runs the enrichment layer with error recovery."""
    from src.layers.enrichment import run_enrichment_layer
    _run_with_recovery("Enrichment", run_enrichment_layer)


def _run_people():
    """Wrapper that runs the people discovery layer with error recovery."""
    from src.layers.people import run_people_layer
    _run_with_recovery("People", run_people_layer)


def _run_email_generation():
    """Wrapper that runs the email generation layer with error recovery."""
    from src.layers.email_generation import run_email_generation_layer
    _run_with_recovery("Email Generation", run_email_generation_layer)


def _run_with_recovery(layer_name, layer_func):
    """
    Runs a layer function in a loop with error recovery. If the layer
    function raises an exception, it logs the error and restarts after
    a short delay. Stops when the shutdown event is set.

    Parameters:
        layer_name: Human-readable name for logging.
        layer_func: The layer function to call. It receives the shutdown
            event, input queue, and output queue as arguments.
    """
    queue_map = {
        "Discovery": (None, discovery_to_enrichment),
        "Enrichment": (discovery_to_enrichment, enrichment_to_people),
        "People": (enrichment_to_people, people_to_email),
        "Email Generation": (people_to_email, None),
    }

    input_queue, output_queue = queue_map[layer_name]

    while not shutdown_event.is_set():
        try:
            layer_func(shutdown_event, input_queue, output_queue)
        except Exception as e:
            if shutdown_event.is_set():
                break
            log_error(f"[{layer_name}] Error: {e}")
            log_status(f"[{layer_name}] Restarting in 10 seconds...")
            # Wait 10 seconds before restarting, checking shutdown every second
            for _ in range(10):
                if shutdown_event.is_set():
                    break
                time.sleep(1)


def _signal_handler(signum, frame):
    """
    Handles SIGINT (Ctrl+C) by setting the shutdown event. This allows
    all layers to finish their current work item before exiting.
    """
    log_status("\nShutdown signal received. Finishing current work...")
    shutdown_event.set()


def _shutdown(threads):
    """
    Waits for all layer threads to finish (with a timeout) and logs
    the shutdown status.

    Parameters:
        threads: List of threading.Thread instances to wait for.
    """
    log_status("Waiting for layers to finish current work (max 30 seconds)...")
    for thread in threads:
        thread.join(timeout=30)
    log_success("Pipeline shut down.")
