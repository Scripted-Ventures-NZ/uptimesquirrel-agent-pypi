"""
Task manager for handling check execution tasks
Manages concurrent execution and result submission
"""
import asyncio
import json
import threading
import time
import logging
import psutil
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from queue import Queue, Empty

from .check_executor import ExecutorRegistry

logger = logging.getLogger('uptimesquirrel-agent.task_manager')


class TaskManager:
    """Manages check execution tasks"""
    
    def __init__(self, agent_config: Dict[str, Any]):
        self.config = agent_config
        self.api_url = agent_config.get('api_url', 'https://agent-api.uptimesquirrel.com')
        self.agent_key = agent_config.get('agent_key')
        self.agent_id = agent_config.get('agent_id')
        # Default raised from 10 to 50: HTTP/ping checks are cheap and 10 was a bottleneck
        # that caused tasks to back up. ThreadPoolExecutor still queues beyond this anyway.
        self.max_concurrent = agent_config.get('max_concurrent_checks', 50)
        # Soft cap on in-flight tasks before we log warnings. We never silently drop
        # below this — see process_pending_tasks. Set generously to avoid false alarms.
        self.soft_task_warn_threshold = max(self.max_concurrent * 4, 200)
        
        self.executor_registry = ExecutorRegistry()
        self.running = True
        self.active_tasks = {}
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent)
        self.result_queue = Queue(maxsize=100)
        
        # Start result sender thread
        self.result_sender_thread = threading.Thread(target=self._result_sender_loop, daemon=True)
        self.result_sender_thread.start()
        
        logger.info(f"TaskManager initialized with max_concurrent={self.max_concurrent}")
        
    def process_pending_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """Process tasks received from the agent-api"""
        # Clean up any completed tasks first so active_tasks reflects reality
        # before we use its length to log overload warnings.
        self._cleanup_completed_tasks()

        for task in tasks:
            try:
                # Check if task is expired
                expires_at = datetime.fromisoformat(task['expires_at'].replace('Z', '+00:00'))
                if datetime.now(timezone.utc) > expires_at:
                    logger.warning(f"Task {task['task_id']} expired, skipping")
                    continue

                # NOTE: We deliberately do NOT gate submission on
                # len(active_tasks) >= max_concurrent here. The previous code
                # silently dropped tasks when the gate tripped, which left the
                # server-side task as 'dispatched' until it expired (5 min) and
                # was the dominant cause of 'expired with executed_at IS NULL'
                # failures. ThreadPoolExecutor has an unbounded internal work
                # queue — extras just wait for a worker to free up. Always
                # submit, always ack.
                in_flight = len(self.active_tasks)
                if in_flight >= self.soft_task_warn_threshold:
                    logger.warning(
                        f"In-flight task count {in_flight} exceeds soft threshold "
                        f"{self.soft_task_warn_threshold}; still submitting "
                        f"{task['task_id']} but agent may be overloaded"
                    )

                # Execute task asynchronously
                future = self.executor.submit(self._execute_task, task)
                self.active_tasks[task['task_id']] = future

                # Acknowledge task receipt
                self._acknowledge_task(task['task_id'])

            except Exception as e:
                logger.error(f"Error processing task {task.get('task_id')}: {e}")

        # Clean up completed tasks
        self._cleanup_completed_tasks()
        
    def _execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a check task"""
        result = {
            'task_id': task['task_id'],
            'check_id': task['check']['check_id'],
            'check_name': task['check'].get('check_name', 'Unknown'),
            'agent_id': self.agent_id,
            'agent_hostname': self.config.get('hostname', 'unknown'),
            'started_at': datetime.now(timezone.utc).isoformat()
        }
        
        try:
            # Get executor for check type
            check_type = task['check']['type']
            executor = self.executor_registry.get(check_type)
            
            if not executor:
                result['ok'] = False
                result['error_message'] = f"Unsupported check type: {check_type}"
            else:
                # Run executor asynchronously
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                exec_result = loop.run_until_complete(
                    executor.execute(task['check']['params'])
                )
                
                loop.close()
                
                # Merge execution result
                result.update(exec_result)
                
        except Exception as e:
            logger.error(f"Error executing task {task['task_id']}: {e}")
            result['ok'] = False
            result['error_message'] = str(e)
            
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        
        # Add system metrics
        result['metrics'] = {
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'memory_mb': psutil.Process().memory_info().rss / 1024 / 1024
        }
        
        # Queue result for sending
        try:
            self.result_queue.put_nowait(result)
        except:
            logger.error(f"Result queue full, dropping result for task {task['task_id']}")
            
        return result
        
    def _acknowledge_task(self, task_id: str) -> None:
        """Acknowledge task receipt to agent-api"""
        try:
            response = requests.post(
                f"{self.api_url}/agent/tasks/{task_id}/ack",
                headers={'X-Agent-Key': self.agent_key},
                timeout=5
            )
            if response.status_code != 200:
                logger.warning(f"Failed to ack task {task_id}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending ack for task {task_id}: {e}")
            
    def _result_sender_loop(self) -> None:
        """Send results back to agent-api"""
        session = requests.Session()
        session.headers.update({
            'X-Agent-Key': self.agent_key,
            'Content-Type': 'application/json'
        })
        
        while self.running:
            try:
                # Get result from queue with timeout
                result = self.result_queue.get(timeout=1)
                self._send_result(session, result)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Result sender error: {e}")
                
    def _send_result(self, session: requests.Session, result: Dict[str, Any]) -> None:
        """Send execution result to agent-api"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = session.post(
                    f"{self.api_url}/agent/tasks/{result['task_id']}/result",
                    json=result,
                    timeout=30
                )
                
                if response.status_code == 200:
                    logger.info(f"Successfully sent result for task {result['task_id']}")
                    return
                else:
                    logger.warning(f"Failed to send result: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Error sending result (attempt {attempt + 1}/{max_retries}): {e}")
                
            # Exponential backoff
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                
    def _cleanup_completed_tasks(self) -> None:
        """Remove completed tasks from active tasks"""
        completed = []
        for task_id, future in self.active_tasks.items():
            if future.done():
                completed.append(task_id)
                
        for task_id in completed:
            del self.active_tasks[task_id]
            
    def update_capabilities(self) -> None:
        """Report agent capabilities to API"""
        capabilities = {
            'check_execution': True,
            'http': True,
            'https': True,
            'tcp': True,
            'ping': True,  # ICMP/PING support (may require root or CAP_NET_RAW)
            'icmp': True,  # Alias for PING
            'supports_advanced': False,  # Agents do NOT support visual workflow checks
            'max_concurrent': self.max_concurrent,
            'home_region': 'us-west-1',  # All results route through us-west-1 infrastructure
            'agent_version': self.config.get('agent_version', '2.0.0')
        }
        
        try:
            response = requests.put(
                f"{self.api_url}/agent/capabilities",
                json=capabilities,
                headers={'X-Agent-Key': self.agent_key},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Successfully reported capabilities")
            else:
                logger.warning(f"Failed to report capabilities: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error reporting capabilities: {e}")
            
    def stop(self) -> None:
        """Stop task manager"""
        self.running = False
        self.executor.shutdown(wait=True)
        logger.info("TaskManager stopped")