"""
Performance measurement utilities for SDOM model initialization profiling.

This module provides classes for tracking time and memory usage during model
initialization and other computationally intensive operations.
"""

import logging
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any


@dataclass
class StepProfile:
    """Stores profiling data for a single step in model initialization."""
    step_name: str
    time_seconds: float = 0.0
    memory_bytes: int = 0
    memory_peak_bytes: int = 0


@dataclass
class ModelInitProfiler:
    """
    Profiler for tracking time and memory usage during model initialization.
    
    Collects timing and memory statistics for each step in the model initialization
    process and provides formatted output as a summary table.
    
    Attributes:
        steps (List[StepProfile]): List of profiled steps with timing and memory data.
        track_memory (bool): Whether to track memory allocation (default: True).
        enabled (bool): Whether profiling is enabled (default: True). When disabled,
            measure_step simply executes the function without measuring.
    
    Example:
        >>> profiler = ModelInitProfiler()
        >>> profiler.start()
        >>> result = profiler.measure_step("Initialize data", load_data, arg1, arg2)
        >>> profiler.measure_step("Process data", process, result)
        >>> profiler.stop()
        >>> profiler.print_summary_table()
    """
    steps: List[StepProfile] = field(default_factory=list)
    track_memory: bool = True
    enabled: bool = True
    _start_time: float = field(default=0.0, repr=False)
    _tracemalloc_started: bool = field(default=False, repr=False)
    
    def start(self):
        """Start the profiler and initialize memory tracking if enabled."""
        if not self.enabled:
            return
        if self.track_memory and not tracemalloc.is_tracing():
            tracemalloc.start()
            self._tracemalloc_started = True
        self._start_time = time.perf_counter()
    
    def stop(self):
        """Stop the profiler and clean up memory tracking."""
        if self._tracemalloc_started:
            tracemalloc.stop()
            self._tracemalloc_started = False
    
    def measure_step(self, step_name: str, func: Callable, *args, **kwargs) -> Any:
        """
        Measure execution time and memory for a single function call.
        
        When profiling is disabled, simply executes the function without measuring.
        
        Args:
            step_name (str): Descriptive name for the step.
            func (callable): Function to execute and measure.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.
        
        Returns:
            The return value of the executed function.
        """
        if not self.enabled:
            return func(*args, **kwargs)
        
        if self.track_memory and tracemalloc.is_tracing():
            tracemalloc.reset_peak()
            mem_before = tracemalloc.get_traced_memory()[0]
        else:
            mem_before = 0
        
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_time = time.perf_counter() - start_time
        
        if self.track_memory and tracemalloc.is_tracing():
            mem_current, mem_peak = tracemalloc.get_traced_memory()
            mem_allocated = mem_current - mem_before
        else:
            mem_allocated = 0
            mem_peak = 0
        
        self.steps.append(StepProfile(
            step_name=step_name,
            time_seconds=elapsed_time,
            memory_bytes=mem_allocated,
            memory_peak_bytes=mem_peak
        ))
        
        return result
    
    def get_total_time(self) -> float:
        """Return total time across all measured steps."""
        return sum(step.time_seconds for step in self.steps)
    
    def get_total_memory(self) -> int:
        """Return total memory allocated across all measured steps."""
        return sum(step.memory_bytes for step in self.steps)
    
    def _format_memory(self, bytes_val: int) -> str:
        """Format memory value in human-readable format."""
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.2f} KB"
        else:
            return f"{bytes_val / (1024 * 1024):.2f} MB"
    
    def print_summary_table(
        self,
        logger: Optional[logging.Logger] = None,
        *,
        title: str = "MODEL INITIALIZATION PROFILING SUMMARY",
    ):
        """
        Print a formatted summary table of all profiled steps.
        
        The table includes step name, time in seconds, percentage of total time,
        and memory allocation information.
        
        Args:
            logger (logging.Logger, optional): Logger to use for output. 
                If None, prints to stdout.
            title (str, optional): Heading rendered between the top separators.
                Defaults to ``"MODEL INITIALIZATION PROFILING SUMMARY"``.
        """
        if not self.enabled or not self.steps:
            return
        
        total_time = self.get_total_time()
        total_memory = self.get_total_memory()
        
        # Define column widths
        name_width = max(len(step.step_name) for step in self.steps) + 2
        name_width = max(name_width, 30)
        
        # Build header
        header = (
            f"{'Step':<{name_width}} | {'Time (s)':>12} | {'Time (%)':>10} | "
            f"{'Memory':>12} | {'Mem (%)':>10}"
        )
        separator = "-" * len(header)
        
        lines = [
            "",
            "=" * len(header),
            title,
            "=" * len(header),
            header,
            separator
        ]
        
        for step in self.steps:
            time_pct = (step.time_seconds / total_time * 100) if total_time > 0 else 0
            mem_pct = (step.memory_bytes / total_memory * 100) if total_memory > 0 else 0
            
            line = (
                f"{step.step_name:<{name_width}} | "
                f"{step.time_seconds:>12.4f} | "
                f"{time_pct:>9.2f}% | "
                f"{self._format_memory(step.memory_bytes):>12} | "
                f"{mem_pct:>9.2f}%"
            )
            lines.append(line)
        
        # Add totals row
        lines.append(separator)
        totals_line = (
            f"{'TOTAL':<{name_width}} | "
            f"{total_time:>12.4f} | "
            f"{'100.00%':>10} | "
            f"{self._format_memory(total_memory):>12} | "
            f"{'100.00%':>10}"
        )
        lines.append(totals_line)
        lines.append("=" * len(header))
        lines.append("")
        
        output = "\n".join(lines)
        
        if logger:
            logger.info(output)
        else:
            print(output)
    
    def get_summary_dict(self) -> dict:
        """
        Return profiling data as a dictionary for programmatic access.
        
        Returns:
            dict: Dictionary containing profiling data with keys:
                - 'steps': List of step data dictionaries
                - 'total_time_seconds': Total time across all steps
                - 'total_memory_bytes': Total memory allocated
        """
        total_time = self.get_total_time()
        total_memory = self.get_total_memory()
        
        return {
            'steps': [
                {
                    'step_name': step.step_name,
                    'time_seconds': step.time_seconds,
                    'time_percentage': (step.time_seconds / total_time * 100) if total_time > 0 else 0,
                    'memory_bytes': step.memory_bytes,
                    'memory_percentage': (step.memory_bytes / total_memory * 100) if total_memory > 0 else 0,
                }
                for step in self.steps
            ],
            'total_time_seconds': total_time,
            'total_memory_bytes': total_memory,
        }
