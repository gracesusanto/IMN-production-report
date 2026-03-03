"""
Async task management for ActivityReport updates.

This module provides asynchronous background processing for expensive
ActivityReport upsert operations to avoid blocking the main request flow.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import List, Set
import time

import app.database as database
from app.service.business_logic import upsert_activity_report


# Global task executor for background processing
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="report_async")

# Track pending tasks to avoid duplicate work
_pending_activity_ids: Set[int] = set()
_pending_lock = asyncio.Lock()

logger = logging.getLogger(__name__)


@contextmanager
def new_database_session():
    """Create a new database session for background tasks."""
    session = database.SessionLocal()
    try:
        yield session
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error in background task: {e}")
        raise
    finally:
        session.close()


async def _async_upsert_activity_report(activity_id: int) -> None:
    """
    Async wrapper for upsert_activity_report that manages its own session.

    This runs the async upsert directly in the event loop.
    """
    import asyncio

    # Add a small delay to ensure the main transaction has committed
    await asyncio.sleep(0.1)

    # Retry logic for race conditions with transaction commits
    max_retries = 3
    retry_delay = 0.5

    for attempt in range(max_retries):
        try:
            with new_database_session() as session:
                await upsert_activity_report(activity_id, session)
                logger.debug(f"Successfully upserted activity_report for activity_id={activity_id}")
                return
        except ValueError as e:
            if "is not completed" in str(e) and attempt < max_retries - 1:
                # Activity might not be committed yet, retry after delay
                logger.debug(f"Activity {activity_id} not ready yet, retrying in {retry_delay}s (attempt {attempt + 1})")
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.warning(f"Activity {activity_id} not found or incomplete after {max_retries} attempts: {e}")
                return  # Don't raise, just log and continue
        except Exception as e:
            logger.error(f"Failed to upsert activity_report for activity_id={activity_id}: {e}")
            raise


async def schedule_activity_report_update(activity_id: int) -> None:
    """
    Schedule an async update for ActivityReport table.

    This function is non-blocking and handles duplicate prevention.

    Args:
        activity_id: The ActivityMesin.id to update in ActivityReport table
    """
    async with _pending_lock:
        # Skip if already pending
        if activity_id in _pending_activity_ids:
            logger.debug(f"Activity {activity_id} already scheduled for async update")
            return

        _pending_activity_ids.add(activity_id)

    try:
        # Run the async operation directly
        await _async_upsert_activity_report(activity_id)

    except Exception as e:
        logger.error(f"Async activity report update failed for activity_id={activity_id}: {e}")

    finally:
        # Always remove from pending set
        async with _pending_lock:
            _pending_activity_ids.discard(activity_id)


async def schedule_multiple_activity_report_updates(activity_ids: List[int]) -> None:
    """
    Schedule multiple ActivityReport updates concurrently.

    This batches multiple updates for better performance when processing
    multiple stopped activities.

    Args:
        activity_ids: List of ActivityMesin.id values to update
    """
    if not activity_ids:
        return

    logger.info(f"Scheduling async updates for {len(activity_ids)} activity reports")

    # Create concurrent tasks for all updates
    tasks = [
        schedule_activity_report_update(activity_id)
        for activity_id in activity_ids
    ]

    # Wait for all updates to complete
    await asyncio.gather(*tasks, return_exceptions=True)


def schedule_activity_report_update_sync(activity_id: int) -> None:
    """
    Synchronous interface for scheduling async ActivityReport updates.

    This can be called from synchronous code to schedule background updates.
    Creates a new event loop if none exists.

    Args:
        activity_id: The ActivityMesin.id to update in ActivityReport table
    """
    try:
        # Try to get current event loop
        loop = asyncio.get_event_loop()

        # Schedule the coroutine as a task (non-blocking)
        task = loop.create_task(schedule_activity_report_update(activity_id))

        # Optional: Add done callback for error handling
        task.add_done_callback(_handle_task_completion)

    except RuntimeError:
        # No event loop running, create new one in thread
        def run_in_thread():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                new_loop.run_until_complete(schedule_activity_report_update(activity_id))
            finally:
                new_loop.close()

        _executor.submit(run_in_thread)


def schedule_multiple_activity_report_updates_sync(activity_ids: List[int]) -> None:
    """
    Synchronous interface for scheduling multiple async ActivityReport updates.

    Args:
        activity_ids: List of ActivityMesin.id values to update
    """
    if not activity_ids:
        return

    try:
        # Try to get current event loop
        loop = asyncio.get_event_loop()

        # Schedule the coroutine as a task (non-blocking)
        task = loop.create_task(schedule_multiple_activity_report_updates(activity_ids))
        task.add_done_callback(_handle_task_completion)

    except RuntimeError:
        # No event loop running, create new one in thread
        def run_in_thread():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                new_loop.run_until_complete(schedule_multiple_activity_report_updates(activity_ids))
            finally:
                new_loop.close()

        _executor.submit(run_in_thread)


def _handle_task_completion(task: asyncio.Task) -> None:
    """Handle task completion and log any exceptions."""
    try:
        task.result()  # This will raise if task failed
    except Exception as e:
        logger.error(f"Async task failed: {e}")


async def wait_for_pending_updates(timeout: float = 30.0) -> bool:
    """
    Wait for all pending ActivityReport updates to complete.

    Useful for testing or graceful shutdown scenarios.

    Args:
        timeout: Maximum time to wait in seconds

    Returns:
        True if all updates completed, False if timeout occurred
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        async with _pending_lock:
            if not _pending_activity_ids:
                return True

        # Wait a bit before checking again
        await asyncio.sleep(0.1)

    # Timeout occurred
    async with _pending_lock:
        remaining = len(_pending_activity_ids)

    logger.warning(f"Timeout waiting for {remaining} pending activity report updates")
    return False


def get_pending_update_count() -> int:
    """
    Get the current number of pending ActivityReport updates.

    Useful for monitoring and debugging.
    """
    return len(_pending_activity_ids)


def shutdown_async_tasks():
    """Shutdown the async task system gracefully."""
    _executor.shutdown(wait=True)
    logger.info("Async task system shutdown complete")